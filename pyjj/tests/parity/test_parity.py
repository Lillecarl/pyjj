"""Conformance scenarios: the same argv through real jj and pyjj-cli
must produce bit-identical repositories (see parity_harness module docs).

Both sides get literally the same command line (the `py=` override exists
only for the asymmetric `git init` destination), so every flag and value
here must exist in pyjj-cli's parser with jj's semantics for the suite to
pass at all.

Revisions are addressed by description glob (`description(glob:"x*")`)
because change ids/commit ids cannot be written into scenarios by hand --
they are an *output* of these tests, not an input. The glob form absorbs
the trailing newline `jj -m` stores in every description.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from parity_harness import DRIVER, RepoPair

pytestmark = pytest.mark.skipif(
    shutil.which(os.environ.get("PYJJ_PARITY_JJ", "jj")) is None,
    reason="jj binary not available",
)


def rev(name: str) -> str:
    return f'description(glob:"{name}*")'


def chain(pair: RepoPair) -> None:
    """base <- one <- two, with base.txt/one.txt/two.txt and bookmark main
    on 'one' -- the shared prefix most scenarios start from."""
    pair.init()
    pair.op(files={"base.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"one.txt": b"one\n"}, jj=["bookmark", "create", "main"])
    pair.op(jj=["new", "-m", "two"])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"])


def test_init_only(pair: RepoPair) -> None:
    pair.init()
    pair.assert_parity()


def test_describe_and_commit_chain(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_parity()


def test_squash_non_wc_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "-r", rev("one"), "--use-destination-message"])
    pair.assert_parity()


def test_rebase_revision_onto_sibling(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    # Rebasing 'one' onto 'side' must graft its descendant 'two' onto
    # one's ORIGINAL parent (real -r treats the moved slot as abandoned),
    # leaving the same rewritten graph on both sides.
    pair.op(jj=["rebase", "-r", rev("one"), "-d", rev("side")])
    pair.assert_parity()


def test_abandon_middle_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["abandon", rev("one")])
    pair.assert_parity()


def test_duplicate_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("one")])
    pair.assert_parity()


def test_bookmark_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.assert_parity()


def test_edit_moves_working_copy(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["edit", rev("base")])
    pair.assert_parity()


def test_commit_describes_and_advances(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"a\n"}, jj=["commit", "-m", "one"])
    pair.assert_parity()


def test_describe_multiple_revisions_shared_message(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["describe", "-r", rev("base"), "-r", rev("one"),
            "-m", "shared description"]
    )
    pair.assert_parity()


def test_describe_stdin_description(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"a\n"}, jj=["describe", "--stdin"], stdin="from stdin\n")
    pair.assert_parity()


def test_restore_all_from_parent(pair: RepoPair) -> None:
    chain(pair)
    # The implicit snapshot absorbs the edit into @ first; the restore
    # then pulls @'s whole tree back to @-'s.
    pair.op(files={"two.txt": b"changed\n"}, jj=["restore"])
    pair.assert_parity()


def test_restore_single_path_between_revisions(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["restore", "--from", rev("base"), "--into", rev("two"), "one.txt"]
    )
    pair.assert_parity()


def test_split_paths_on_wc(pair: RepoPair) -> None:
    pair.init()
    pair.op(
        files={"base.txt": b"base\n", "one.txt": b"one\n"},
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["split", "base.txt", "-m", "first"])
    pair.assert_parity()


def test_new_merge_two_parents(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(jj=["new", rev("one"), rev("side"), "-m", "merge"])
    pair.assert_parity()


# -- operation-level commands ------------------------------------------------
#
# Both CLIs commit an identical operation structure per step: when the
# working copy is dirty, each emits its own "snapshot working copy"
# operation followed by the command's operation (verified against real
# jj 0.43's op log). Undoing across file-write boundaries is therefore
# fair game -- see the *_crossing scenarios below.


def test_undo_bookmark_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.op(jj=["undo"])
    pair.assert_parity()


def test_undo_then_redo(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.op(jj=["undo"])
    pair.op(jj=["redo"])
    pair.assert_parity()


def test_undo_describe(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.assert_parity()


def test_undo_twice(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "create", "extra"])
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.op(jj=["undo"])
    pair.assert_parity()


def test_op_restore_skips_last_operation(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "create", "extra"])
    # Depth 1 = the state before the last logical operation: the new
    # empty commit disappears, the bookmark creation stays.
    pair.op(jj=["new", "-m", "transient"])
    pair.op_restore(1)
    pair.assert_parity()


def test_op_restore_across_wc_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", "-m", "later"])
    # Back two ops lands on the pre-chain-head working copy; both sides
    # must check the on-disk working copy back out to it.
    pair.op_restore(2)
    pair.assert_parity()


def test_undo_across_file_write(pair: RepoPair) -> None:
    chain(pair)
    # The dirty-wc describe emits "snapshot working copy" then "describe
    # commit" on both sides; one undo removes only the describe.
    pair.op(files={"two.txt": b"changed\n"}, jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.assert_parity()


def test_undo_twice_past_describe_onto_snapshot(pair: RepoPair) -> None:
    chain(pair)
    pair.op(files={"two.txt": b"changed\n"}, jj=["describe", "-m", "renamed"])
    pair.op(jj=["bookmark", "set", "main", "-r", rev("renamed")])
    pair.op(jj=["undo"])
    # The second undo removes the describe; the standalone snapshot op is
    # now head on both sides.
    pair.op(jj=["undo"])
    pair.assert_parity()


def test_undo_three_times_through_snapshot_op(pair: RepoPair) -> None:
    chain(pair)
    pair.op(files={"two.txt": b"changed\n"}, jj=["describe", "-m", "renamed"])
    # The third undo removes the "snapshot working copy" operation itself,
    # reverting the absorbed tree change on both sides.
    pair.op(jj=["undo"])
    pair.op(jj=["undo"])
    pair.op(jj=["undo"])
    pair.assert_parity()


# -- conflicts ----------------------------------------------------------------


def conflict_pair(pair: RepoPair) -> None:
    """base <- one, two (siblings editing the same line); @ = merge with a
    2-sided conflict on f.txt."""
    pair.init()
    pair.op(files={"f.txt": b"line1\nline2\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"f.txt": b"ONE\nline2\n"}, jj=["status"])
    pair.op(jj=["new", rev("base"), "-m", "two"])
    pair.op(files={"f.txt": b"TWO\nline2\n"}, jj=["status"])
    pair.op(
        jj=["new", rev("one"), rev("two"), "-m", "merge"]
    )


def test_new_merge_conflict(pair: RepoPair) -> None:
    conflict_pair(pair)
    # The extractor hashes `jj file show` output, which materializes the
    # conflicted path deterministically -- so byte parity here covers the
    # whole conflict object.
    pair.assert_parity()


def test_resolve_by_editing_working_copy(pair: RepoPair) -> None:
    conflict_pair(pair)
    # Writing marker-free text and letting any command's implicit snapshot
    # pick it up is how real jj resolves non-interactively too.
    for side in ("cli", "py"):
        pair.write_wc_file(side, "f.txt", b"RESOLVED\nline2\n")
    pair.op(jj=["status"])
    pair.assert_parity()


def test_partial_resolution_keeps_conflict(pair: RepoPair) -> None:
    conflict_pair(pair)
    # Marker text embeds repo-local change ids, so each side edits its own
    # copy: append a line inside one conflict side. Both sides must parse
    # their edited text back into an equivalent (still-conflicted) shape.
    for side in ("cli", "py"):
        text = pair.read_wc_file(side, "f.txt")
        assert b"<<<<<<<" in text
        pair.write_wc_file(side, "f.txt", text.replace(b"\nline2\n", b"\nline2 edited\n"))
    pair.op(jj=["status"])
    pair.assert_parity()


# -- resolve (3-way merge tool) ------------------------------------------------
#
# merge-tools.parity-merge / parity-write (scratch-HOME config, loaded by
# both sides) point at the scripted merge tool; PARITY_MERGE_SPEC arms it.
# This is real jj's own resolve protocol: $base/$left/$right/$output
# files per conflicted path; the output file's final content decides.


def multi_hunk_conflict(pair: RepoPair) -> None:
    """Like conflict_pair, but the two siblings change TWO separate lines,
    so the materialized conflict carries two distinct marker regions."""
    pair.init()
    pair.op(files={"f.txt": b"a\nm\nz\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"f.txt": b"A1\nm\nZ1\n"}, jj=["status"])
    pair.op(jj=["new", rev("base"), "-m", "two"])
    pair.op(files={"f.txt": b"A2\nm\nZ2\n"}, jj=["status"])
    pair.op(jj=["new", rev("one"), rev("two"), "-m", "merge"])


def test_resolve_list_shows_conflicts(pair: RepoPair) -> None:
    conflict_pair(pair)
    pair.op(jj=["resolve", "-l"])
    # --list must not touch state at all.
    pair.assert_parity()


def test_resolve_no_conflicts_is_an_error(pair: RepoPair) -> None:
    chain(pair)
    rc = pair.op(jj=["resolve"], may_fail=True)
    assert rc != 0
    pair.assert_parity()


def test_resolve_partial_region_leaves_conflict(pair: RepoPair) -> None:
    multi_hunk_conflict(pair)
    # Resolving only the first region of a two-region conflict still
    # leaves the file conflicted (partial resolution): op recorded, but
    # real jj exits nonzero afterwards.
    pair.op(
        jj=["resolve", "--tool", "parity-merge"],
        merge_spec={"op": "resolve_first_region", "text": "chosen-a"},
        may_fail=True,
    )
    pair.assert_parity()


def test_resolve_pick_left_resolves_fully(pair: RepoPair) -> None:
    multi_hunk_conflict(pair)
    # A whole-side pick collapses every region of both hunks at once.
    pair.op(
        jj=["resolve", "--tool", "parity-merge"],
        merge_spec={"op": "pick_left"},
    )
    pair.assert_parity()


def test_resolve_verbatim_output_is_taken_as_is(pair: RepoPair) -> None:
    conflict_pair(pair)
    # parity-write runs without merge-tool-edits-conflict-markers: $output
    # starts empty and its final bytes become the resolved file verbatim.
    pair.op(
        jj=["resolve", "--tool", "parity-write"],
        merge_spec={"op": "pick_right"},
    )
    pair.assert_parity()


def test_resolve_unchanged_output_still_commits(pair: RepoPair) -> None:
    conflict_pair(pair)
    # Upstream's EmptyOrUnchanged path: nothing resolved, but the commit
    # is rewritten (committer-timestamp bump) and the operation recorded --
    # then the command fails.
    pair.op(
        jj=["resolve", "--tool", "parity-merge"],
        merge_spec={"op": "unchanged"},
        may_fail=True,
    )
    pair.assert_parity()


def test_resolve_specific_file_only(pair: RepoPair) -> None:
    """Two conflicted files; FILESETS restricts the tool run to one."""
    pair.init()
    pair.op(files={"f.txt": b"f0\n", "g.txt": b"g0\n"},
            jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"f.txt": b"F1\n", "g.txt": b"G1\n"}, jj=["status"])
    pair.op(jj=["new", rev("base"), "-m", "two"])
    pair.op(files={"f.txt": b"F2\n", "g.txt": b"G2\n"}, jj=["status"])
    pair.op(jj=["new", rev("one"), rev("two"), "-m", "merge"])
    pair.op(jj=["resolve", "--tool", "parity-write", "g.txt"],
            merge_spec={"op": "pick_right"})
    # f.txt stays conflicted; only g.txt resolved.
    pair.assert_parity()


# -- flag combinations --------------------------------------------------------


def test_bookmark_create_multiple_names(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "create", "alpha", "beta"])
    pair.assert_parity()


def test_abandon_two_revisions_at_once(pair: RepoPair) -> None:
    chain(pair)
    # Includes @ itself, so both sides must also produce a fresh empty
    # working-copy commit on top.
    pair.op(jj=["abandon", rev("one"), rev("two")])
    pair.assert_parity()


def test_duplicate_two_revisions_at_once(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(jj=["duplicate", rev("one"), rev("side")])
    pair.assert_parity()


def test_squash_with_explicit_message(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "-r", rev("one"), "-m", "explicit message"])
    pair.assert_parity()


def test_describe_ancestor_rebases_descendants(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["describe", "-r", rev("base"), "-m", "renamed base"])
    pair.assert_parity()


# -- editor-driven flows -------------------------------------------------------
#
# $EDITOR is the scripted parity-editor (see editor.py); a spec arms it
# per invocation. An unexpected editor launch without a spec fails loudly
# on both sides, so these scenarios can't silently skip the mechanism.


def test_describe_via_editor(pair: RepoPair) -> None:
    pair.init()
    pair.op(
        files={"a.txt": b"a\n"},
        jj=["describe"],
        editor_spec={"op": "set", "value": "edited description\n"},
    )
    pair.assert_parity()


def test_describe_editor_append_keeps_typed_text(pair: RepoPair) -> None:
    # Appending proves the buffer actually round-tripped through the
    # editor: whatever survives cleanup must be identical on both sides.
    pair.init()
    pair.op(
        files={"a.txt": b"a\n"},
        jj=["describe"],
        editor_spec={"op": "append", "value": "typed by the fake editor\n"},
    )
    pair.assert_parity()


def test_commit_via_editor(pair: RepoPair) -> None:
    pair.init()
    pair.op(
        files={"a.txt": b"a\n"},
        jj=["commit"],
        editor_spec={"op": "set", "value": "committed via editor\n"},
    )
    pair.assert_parity()


def test_squash_combines_messages_via_editor(pair: RepoPair) -> None:
    chain(pair)
    # Both source ('one') and destination ('base') have descriptions, so
    # plain squash opens the combining editor; dropping its JJ: comment
    # lines keeps both descriptions in file order.
    pair.op(jj=["squash", "-r", rev("one")],
            editor_spec={"op": "drop_jj_comments"})
    pair.assert_parity()


def test_split_first_half_message_via_editor(pair: RepoPair) -> None:
    pair.init()
    pair.op(
        files={"base.txt": b"base\n", "one.txt": b"one\n"},
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["split", "base.txt"],
            editor_spec={"op": "drop_jj_comments"})
    pair.assert_parity()


# -- diff-editor flows ---------------------------------------------------------
#
# merge-tools.parity-diff (scratch-HOME config, loaded by both sides)
# points at the scripted dir-based diff tool; PARITY_DIFF_SPEC arms it.
# This is real jj's own protocol: $left/$right directories holding the
# changed paths, result = a snapshot of the right directory.


def two_file_change(pair: RepoPair) -> None:
    """base <- work, where 'work' adds one.txt AND two.txt in one commit."""
    pair.init()
    pair.op(files={"base.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "work"])
    pair.op(files={"one.txt": b"one\n", "two.txt": b"two\n"}, jj=["status"])


def test_split_via_diff_tool_selects_whole_files(pair: RepoPair) -> None:
    two_file_change(pair)
    pair.op(
        jj=["split", "--tool", "parity-diff", "-m", "first"],
        diff_spec={"op": "keep", "paths": ["one.txt"]},
    )
    pair.assert_parity()


def test_split_diff_tool_partial_edit_is_verbatim(pair: RepoPair) -> None:
    two_file_change(pair)
    # Editing a single line inside the right directory selects that file
    # with the EDITED bytes -- fidelity beyond whole-file selection.
    pair.op(
        jj=["split", "--tool", "parity-diff", "-m", "first"],
        diff_spec={"op": "edit",
                   "edits": [{"path": "one.txt",
                              "find": "one", "replace": "one-edited"}]},
    )
    pair.assert_parity()


def test_split_diff_tool_dropped_file_stays_in_remainder(pair: RepoPair) -> None:
    two_file_change(pair)
    pair.op(
        jj=["split", "--tool", "parity-diff", "-m", "first"],
        diff_spec={"op": "drop", "paths": ["two.txt"]},
    )
    pair.assert_parity()


def test_diffedit_rewrites_destination(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["diffedit", "--tool", "parity-diff"],
        diff_spec={"op": "edit",
                   "edits": [{"path": "two.txt",
                              "find": "two", "replace": "TWO-edited"}]},
    )
    pair.assert_parity()


# -- absorb -------------------------------------------------------------------

def test_absorb_moves_change_into_parent(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"line1\nline2\nline3\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"line1\nLINE2-MODIFIED\nline3\n"}, jj=["status"])
    pair.op(jj=["absorb", "--from", "@", "--into", rev("base")])
    pair.assert_parity()


def test_absorb_default_mutable_destination(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"line1\nline2\nline3\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"line1\nLINE2-MODIFIED\nline3\n"}, jj=["status"])
    pair.op(jj=["absorb"])
    pair.assert_parity()


def test_absorb_with_path_filter(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"a1\n", "b.txt": b"b1\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"a1-changed\n", "b.txt": b"b1-changed\n"}, jj=["status"])
    pair.op(jj=["absorb", "--into", rev("base"), "a.txt"])
    pair.assert_parity()


def test_absorb_keeps_described_source(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"line1\nline2\nline3\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "keep me"])
    pair.op(files={"a.txt": b"line1\nLINE2-MODIFIED\nline3\n"}, jj=["status"])
    pair.op(jj=["absorb", "--into", rev("base")])
    pair.assert_parity()


# -- fix ----------------------------------------------------------------------

def _add_fix_tool(pair: RepoPair) -> None:
    """Inject a trivial fix tool (tr a-z A-Z) into the pair's scratch config."""
    config_path = pair.home / ".config" / "jj" / "config.toml"
    with open(config_path, "a") as f:
        f.write('\n[fix.tools.trivial]\ncommand = ["tr", "a-z", "A-Z"]\npatterns = ["glob:\'**/*.txt\'"]\n')


def test_fix_basic(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"hello\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"hello world\n"}, jj=["status"])
    pair.op(jj=["fix"])
    pair.assert_parity()


def test_fix_with_path_filter(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"a\n", "b.txt": b"b\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"a changed\n", "b.txt": b"b changed\n"}, jj=["status"])
    pair.op(jj=["fix", "a.txt"])
    pair.assert_parity()


def test_fix_with_source_filter(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"hello\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "child"])
    pair.op(files={"a.txt": b"hello world\n"}, jj=["status"])
    pair.op(jj=["fix", "-s", rev("base")])
    pair.assert_parity()


def test_fix_propagates_to_descendant(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"a\n", "b.txt": b"b\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"b.txt": b"b changed\n"}, jj=["status"])
    pair.op(jj=["describe", "-m", "child"])
    # Fixing base's a.txt should propagate to child even though child didn't touch a.txt
    pair.op(jj=["fix", "-s", rev("base")])
    pair.assert_parity()


# -- revert -------------------------------------------------------------------

def test_revert_single_onto_parent(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"hello\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"hello\nworld\n"}, jj=["status"])
    pair.op(jj=["revert", "-r", rev("B"), "--onto", rev("A")])
    pair.assert_parity()


def test_revert_onto_self(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"hello\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"hello\nworld\n"}, jj=["status"])
    pair.op(jj=["revert", "-r", rev("B"), "--onto", rev("B")])
    pair.assert_parity()


def test_revert_multiple_in_reverse_topological(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"a\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"a\nb\n"}, jj=["status"])
    pair.op(jj=["new", "-m", "C"])
    pair.op(files={"file.txt": b"a\nb\nc\n"}, jj=["status"])
    # Revert B and C onto A (B is parent of C, so C should be reverted first)
    pair.op(jj=["revert", "-r", rev("B"), "-r", rev("C"), "--onto", rev("A")])
    pair.assert_parity()


def test_revert_insert_after(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"hello\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"hello\nworld\n"}, jj=["status"])
    pair.op(jj=["new", "-m", "C"])
    pair.op(files={"file.txt": b"hello\nworld\nmore\n"}, jj=["status"])
    # Revert B insert-after A (A's child C should be rebased onto the revert)
    pair.op(jj=["revert", "-r", rev("B"), "--insert-after", rev("A")])
    pair.assert_parity()


# -- git ----------------------------------------------------------------------

def _make_bare_remote(base: Path) -> Path:
    """Create a bare git remote with a single branch 'main' seeded with one commit."""
    remote_dir = base / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote_dir)], check=True, capture_output=True)
    seed_dir = base / "seed"
    subprocess.run(["git", "init", "-b", "main", str(seed_dir)], check=True, capture_output=True)
    (seed_dir / "file.txt").write_text("hello\n")
    env = {**os.environ, "GIT_EDITOR": "true", "EDITOR": "true"}
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", "-c", "tag.gpgsign=false", "add", "file.txt"],
        cwd=str(seed_dir), check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", "-c", "tag.gpgsign=false", "commit", "-m", "seed"],
        cwd=str(seed_dir), check=True, capture_output=True, env=env,
    )
    subprocess.run(["git", "push", str(remote_dir), "main"], cwd=str(seed_dir), check=True, capture_output=True, env=env)
    return remote_dir


def test_git_clone(pair: RepoPair) -> None:
    # Clone via both CLIs from the same bare remote and assert parity.
    # This is the only git test that doesn't use pair.init() — it creates its own repos.
    base = Path(tempfile.mkdtemp())
    try:
        remote = _make_bare_remote(base)
        root = pair.root
        cli_dest = root / "cli-clone"
        py_dest = root / "py-clone"
        env = pair._env(bump=False)
        subprocess.run([pair.jj_bin, "git", "clone", str(remote), str(cli_dest)], check=True, capture_output=True, env=env)
        pair._run([sys.executable, str(DRIVER), str(py_dest), "git", "clone", str(remote), str(py_dest)], env, cwd=py_dest.parent)
        got_cli = pair._extract_repo(cli_dest)
        got_py = pair._extract_repo(py_dest)
        if got_cli != got_py:
            import difflib, json
            a = json.dumps(got_cli, indent=1, sort_keys=True).splitlines()
            b = json.dumps(got_py, indent=1, sort_keys=True).splitlines()
            diff = "\n".join(difflib.unified_diff(a, b, "cli", "py", lineterm=""))
            raise AssertionError(f"git clone repos diverged:\n{diff}")
    finally:
        import shutil
        shutil.rmtree(str(base), ignore_errors=True)


def test_git_fetch(pair: RepoPair) -> None:
    base = Path(tempfile.mkdtemp())
    try:
        remote = _make_bare_remote(base)
        pair.init()
        pair.op(jj=["git", "remote", "add", "origin", str(remote)])
        pair.op(jj=["git", "fetch"])
        pair.assert_parity()
    finally:
        import shutil
        shutil.rmtree(str(base), ignore_errors=True)


def test_git_push(pair: RepoPair) -> None:
    base = Path(tempfile.mkdtemp())
    try:
        remote = _make_bare_remote(base)
        pair.init()
        pair.op(jj=["git", "remote", "add", "origin", str(remote)])
        pair.op(jj=["git", "fetch"])
        pair.op(files={"new.txt": b"new\n"}, jj=["describe", "-m", "new"])
        pair.op(jj=["bookmark", "create", "mybranch"])
        pair.op(jj=["git", "push", "--remote", "origin", "-b", "mybranch"])
        pair.assert_parity()
    finally:
        import shutil
        shutil.rmtree(str(base), ignore_errors=True)


def test_git_remote_add_list_remove(pair: RepoPair) -> None:
    pair.init()
    pair.op(jj=["git", "remote", "add", "origin", "https://example.com/repo.git"])
    pair.op(jj=["git", "remote", "add", "upstream", "https://example.com/upstream.git"])
    pair.op(jj=["git", "remote", "list"])
    pair.op(jj=["git", "remote", "remove", "upstream"])
    pair.assert_parity()
