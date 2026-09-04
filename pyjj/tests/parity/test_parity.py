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


def bisect_line(pair: RepoPair, count: int) -> None:
    """`count` commits where `n.txt` holds the commit's index."""
    pair.init()
    pair.op(files={"n.txt": b"0\n"}, jj=["describe", "-m", "c0"])
    for i in range(1, count):
        pair.op(jj=["new", "-m", f"c{i}"])
        pair.op(files={"n.txt": f"{i}\n".encode()}, jj=["status"])


def bisect_predicate(tmp_path, cutoff: int) -> str:
    """A predicate script that calls index >= cutoff 'bad'.

    It lives outside both repos on purpose: bisection checks out a
    different tree at every step, so a script stored in the working copy
    would vanish after the first one.
    """
    script = tmp_path / "bisect_check.py"
    script.write_text(
        "import pathlib, sys\n"
        "n = int(pathlib.Path('n.txt').read_text())\n"
        f"sys.exit(1 if n >= {cutoff} else 0)\n"
    )
    return str(script)


def test_bisect_run(pair: RepoPair, tmp_path) -> None:
    """`bisect run` must leave both repos in the same state.

    Bisection is the one flow that writes commits from inside a loop --
    one `check_out` per candidate -- so the repos only match if both
    sides evaluate the same candidates in the same order.
    """
    bisect_line(pair, 8)
    script = bisect_predicate(tmp_path, cutoff=5)
    pair.op(jj=["bisect", "run", "--range", "root()..@",
                sys.executable, script])
    pair.assert_parity()


def test_bisect_run_find_good(pair: RepoPair, tmp_path) -> None:
    bisect_line(pair, 8)
    script = bisect_predicate(tmp_path, cutoff=5)
    pair.op(jj=["bisect", "run", "--find-good", "--range", "root()..@",
                sys.executable, script])
    pair.assert_parity()


def test_bisect_run_skip(pair: RepoPair, tmp_path) -> None:
    """Exit 125 skips, so no candidate is ever marked good or bad."""
    bisect_line(pair, 6)
    script = tmp_path / "bisect_skip.py"
    script.write_text("import sys\nsys.exit(125)\n")
    pair.op(jj=["bisect", "run", "--range", "root()..@",
                sys.executable, str(script)])
    pair.assert_parity()


# -- operation log family -----------------------------------------------
#
# `op log`, `op show` and `op diff` only read. Parity for them is the
# claim that they exit 0 on both sides and leave the repository exactly
# as they found it -- a renderer that snapshots differently, or crashes,
# fails here. The operation log itself is deliberately not compared:
# snapshot-op folding differs between the two drivers by design (see the
# harness module docs).


def test_op_log_leaves_the_repo_alone(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["op", "log"])
    pair.assert_parity()


def test_op_show_leaves_the_repo_alone(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["op", "show"])
    pair.assert_parity()


def test_op_show_named_operation(pair: RepoPair) -> None:
    """Op ids differ between the repos, so each side names its own."""
    chain(pair)
    pair.op(
        jj=["op", "show", pair.op_id("cli", 1)],
        py=["op", "show", pair.op_id("py", 1)],
    )
    pair.assert_parity()


def test_op_diff_leaves_the_repo_alone(pair: RepoPair) -> None:
    """With no arguments, the diff is the newest operation against its
    parent."""
    chain(pair)
    pair.op(jj=["op", "diff"])
    pair.assert_parity()


def test_op_diff_named_operation(pair: RepoPair) -> None:
    """Op ids differ between the repos, so each side names its own."""
    chain(pair)
    pair.op(
        jj=["op", "diff", "--operation", pair.op_id("cli", 1)],
        py=["op", "diff", "--operation", pair.op_id("py", 1)],
    )
    pair.assert_parity()


def test_op_diff_from_and_to(pair: RepoPair) -> None:
    """A range of operations, not just one against its parent."""
    chain(pair)
    pair.op(
        jj=["op", "diff", "--from", pair.op_id("cli", 3),
            "--to", pair.op_id("cli", 1)],
        py=["op", "diff", "--from", pair.op_id("py", 3),
            "--to", pair.op_id("py", 1)],
    )
    pair.assert_parity()


def test_operation_long_form_diff(pair: RepoPair) -> None:
    """`jj operation diff` is the same command as `jj op diff`."""
    chain(pair)
    pair.op(jj=["operation", "diff"])
    pair.assert_parity()


def test_operation_long_form_log(pair: RepoPair) -> None:
    """`jj operation` is the same command as `jj op`."""
    chain(pair)
    pair.op(jj=["operation", "log"])
    pair.assert_parity()


def test_op_abandon_old_operations(pair: RepoPair) -> None:
    """Abandoning old operations drops history, not repository state."""
    chain(pair)
    pair.op(
        jj=["op", "abandon", f"..{pair.op_id('cli', 2)}"],
        py=["op", "abandon", f"..{pair.op_id('py', 2)}"],
    )
    pair.assert_parity()


# -- bookmarks ----------------------------------------------------------
#
# `chain()` leaves bookmark `main` on the commit described "one".


def test_bookmark_delete(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "delete", "main"])
    pair.assert_parity()


def test_bookmark_forget(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "forget", "main"])
    pair.assert_parity()


def test_bookmark_rename(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "rename", "main", "trunk"])
    pair.assert_parity()


def test_bookmark_move_to_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "move", "main", "--to", rev("two")])
    pair.assert_parity()


def test_bookmark_list_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "list"])
    pair.assert_parity()


# -- rebase modes -------------------------------------------------------


def test_rebase_source_onto_grandparent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-s", rev("two"), "-d", rev("base")])
    pair.assert_parity()


def test_rebase_branch_onto_grandparent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-b", rev("two"), "-d", rev("base")])
    pair.assert_parity()


def test_rebase_insert_after(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-r", rev("two"), "--insert-after", rev("base")])
    pair.assert_parity()


def test_rebase_insert_before(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-r", rev("two"), "--insert-before", rev("one")])
    pair.assert_parity()


# -- squash and restore variants ----------------------------------------


def test_squash_working_copy_into_parent(pair: RepoPair) -> None:
    """`-u` is `--use-destination-message`: no editor, so no prompt."""
    chain(pair)
    pair.op(jj=["squash", "-u"])
    pair.assert_parity()


def test_squash_from_into_named_revisions(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "--from", rev("two"), "--into", rev("one"), "-u"])
    pair.assert_parity()


def test_restore_into_named_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["restore", "--into", rev("two"), "--from", rev("base")])
    pair.assert_parity()


# -- working-copy navigation --------------------------------------------


def test_prev_moves_to_the_parent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["prev"])
    pair.assert_parity()


def test_prev_with_edit_moves_onto_the_parent(pair: RepoPair) -> None:
    """`--edit` moves onto the parent itself, one step less far back than
    the default, which lands a NEW commit below it."""
    chain(pair)
    pair.op(jj=["prev", "--edit"])
    pair.assert_parity()


def test_prev_with_an_offset(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["prev", "2", "--edit"])
    pair.assert_parity()


def test_next_moves_onto_the_sibling_line(pair: RepoPair) -> None:
    """`next` walks forward from `@`'s PARENT and skips `@` itself, so
    from a sibling branch it lands on the other line of development."""
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(jj=["next"])
    pair.assert_parity()


def test_next_with_edit_moves_onto_the_descendant(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["edit", rev("base")])
    pair.op(jj=["next", "--edit"])
    pair.assert_parity()


def test_next_without_a_descendant_fails_on_both(pair: RepoPair) -> None:
    """At the tip there is nothing to move to. Both sides must refuse,
    and neither may change the repository while refusing."""
    chain(pair)
    pair.op(jj=["next"], may_fail=True)
    pair.assert_parity()


def test_next_refuses_when_the_working_copy_has_children(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["edit", rev("base")])
    pair.op(jj=["next"], may_fail=True)
    pair.assert_parity()


# -- new: graph insertion -----------------------------------------------


def test_new_insert_after(pair: RepoPair) -> None:
    """`-A` puts the change between its target and that target's
    children, which are rebased onto it."""
    chain(pair)
    pair.op(jj=["new", "--insert-after", rev("one"), "-m", "inserted"])
    pair.assert_parity()


def test_new_insert_before(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", "--insert-before", rev("two"), "-m", "inserted"])
    pair.assert_parity()


def test_new_no_edit_keeps_the_working_copy(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", "--no-edit", "-m", "detached"])
    pair.assert_parity()


# -- file commands ------------------------------------------------------


def test_file_list_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "list"])
    pair.assert_parity()


def test_file_show_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "show", "base.txt"])
    pair.assert_parity()


def test_file_annotate_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "annotate", "base.txt"])
    pair.assert_parity()


def test_file_search_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "search", "-p", "base"])
    pair.assert_parity()


def test_file_chmod_executable(pair: RepoPair) -> None:
    """The executable bit is part of the git tree, so a divergence here
    changes the commit id."""
    chain(pair)
    pair.op(jj=["file", "chmod", "x", "two.txt"])
    pair.assert_parity()


def test_file_chmod_back_to_normal(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "chmod", "x", "two.txt"])
    pair.op(jj=["file", "chmod", "n", "two.txt"])
    pair.assert_parity()


def test_file_track_is_a_no_op_by_default(pair: RepoPair) -> None:
    """`snapshot.auto-track` defaults to `all()`, so tracking an already
    tracked path changes nothing."""
    chain(pair)
    pair.op(jj=["file", "track", "two.txt"])
    pair.assert_parity()


def test_file_untrack_an_ignored_path(pair: RepoPair) -> None:
    """`file untrack` drops a path from the tree but leaves it on disk."""
    chain(pair)
    pair.op(files={".gitignore": b"two.txt\n"}, jj=["status"])
    pair.op(jj=["file", "untrack", "two.txt"])
    pair.assert_parity()
    for side in ("cli", "py"):
        assert pair.read_wc_file(side, "two.txt") == b"two\n"


def test_file_untrack_refuses_a_tracked_path(pair: RepoPair) -> None:
    """A path that is not ignored comes straight back, so both sides
    must refuse rather than silently doing nothing."""
    chain(pair)
    pair.op(jj=["file", "untrack", "two.txt"], may_fail=True)
    pair.assert_parity()


# -- sparse checkouts ---------------------------------------------------


def test_sparse_list_is_read_only(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["sparse", "list"])
    pair.assert_parity()


def test_sparse_set_narrows_the_working_copy(pair: RepoPair) -> None:
    """Narrowing removes paths from disk but not from the commit."""
    chain(pair)
    pair.op(jj=["sparse", "set", "--clear", "--add", "base.txt"])
    pair.assert_parity()


def test_sparse_set_then_edit_only_touches_the_visible_path(pair: RepoPair) -> None:
    """A snapshot taken through a narrowed working copy must not drop the
    paths that are no longer materialized."""
    chain(pair)
    pair.op(jj=["sparse", "set", "--clear", "--add", "base.txt"])
    pair.op(files={"base.txt": b"base edited\n"}, jj=["describe", "-m", "narrow"])
    pair.assert_parity()


def test_sparse_reset_restores_everything(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["sparse", "set", "--clear", "--add", "base.txt"])
    pair.op(jj=["sparse", "reset"])
    pair.assert_parity()


# -- read-only smoke ----------------------------------------------------
#
# These render; they must not perturb the repository while doing it.


@pytest.mark.parametrize(
    "argv",
    [
        ["log"],
        ["diff"],
        ["show"],
        ["status"],
        ["evolog"],
        ["root"],
        ["version"],
        ["git", "root"],
        ["git", "colocation", "status"],
        ["workspace", "list"],
        ["workspace", "root"],
        ["tag", "list"],
        ["config", "get", "user.name"],
    ],
    ids=lambda a: "_".join(a),
)
def test_read_only_command_does_not_perturb_the_repo(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


# -- tags ---------------------------------------------------------------
#
# Tags are refs, not part of any commit id, so the harness compares them
# explicitly (`tags` in the extracted per-commit state).


def test_tag_set(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.assert_parity()


def test_tag_delete(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.op(jj=["tag", "delete", "v1"])
    pair.assert_parity()


def test_tag_set_then_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.op(jj=["tag", "set", "v1", "--allow-move", "-r", rev("two")])
    pair.assert_parity()


def test_tag_set_refuses_to_move_without_the_flag(pair: RepoPair) -> None:
    """A tag is meant to stay put: moving it needs `--allow-move`."""
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.op(jj=["tag", "set", "v1", "-r", rev("two")], may_fail=True)
    pair.assert_parity()


# -- workspaces ---------------------------------------------------------
#
# Workspace paths are given relative to the repo, so the same argv works
# on both sides even though the two repos live in different directories.
# `working_copies` in the extracted state carries the workspace names.


def test_workspace_add(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "add", "--name", "second", "../second"])
    pair.assert_parity()


def test_workspace_add_then_forget(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "add", "--name", "second", "../second"])
    pair.op(jj=["workspace", "forget", "second"])
    pair.assert_parity()


def test_workspace_rename(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "rename", "renamed"])
    pair.assert_parity()


def test_workspace_add_at_a_named_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "add", "--name", "second", "-r", rev("one"),
                "../second"])
    pair.assert_parity()


# -- git refs and remote-tracking bookmarks -----------------------------
#
# `git export`/`import` move refs inside the backing git repository, and
# refs are not part of any commit id. These scenarios therefore compare
# the git refs directly, on top of the usual repository comparison.


def git_refs(pair: RepoPair, side: str) -> dict[str, str]:
    """Every ref in one side's backing git repository.

    Read-only git against the path `jj git root` reports -- the parity
    harness never writes through git.
    """
    repo = pair.cli_repo if side == "cli" else pair.py_repo
    root = subprocess.run(
        [pair.jj_bin, "-R", str(repo), "--no-pager", "git", "root"],
        capture_output=True, text=True, check=True, cwd=str(repo),
    ).stdout.strip()
    out = subprocess.run(
        ["git", "-C", root, "for-each-ref", "--format=%(refname) %(objectname)"],
        capture_output=True, text=True, check=True,
    ).stdout
    return dict(line.split(" ", 1) for line in out.splitlines() if line)


def assert_ref_parity(pair: RepoPair) -> None:
    cli, py = git_refs(pair, "cli"), git_refs(pair, "py")
    assert cli == py, f"git refs diverged:\ncli: {cli}\npy:  {py}"


def test_git_export_writes_bookmarks_as_git_refs(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "export"])
    pair.assert_parity()
    assert_ref_parity(pair)
    assert any(name.startswith("refs/heads/main") for name in git_refs(pair, "cli"))


def test_git_import_after_export_is_a_no_op(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "export"])
    pair.op(jj=["git", "import"])
    pair.assert_parity()
    assert_ref_parity(pair)


def test_git_export_after_bookmark_delete(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "export"])
    pair.op(jj=["bookmark", "delete", "main"])
    pair.op(jj=["git", "export"])
    pair.assert_parity()
    assert_ref_parity(pair)
    assert not any(n.startswith("refs/heads/main") for n in git_refs(pair, "cli"))


UNIMPLEMENTED = pytest.mark.xfail(
    strict=True, reason="pyjj-cli does not implement this jj command yet",
)


@UNIMPLEMENTED
def test_git_colocation_enable(pair: RepoPair) -> None:
    """Colocation puts a real `.git` beside `.jj`, so git refs must match
    afterwards too."""
    chain(pair)
    pair.op(jj=["git", "colocation", "enable"])
    pair.assert_parity()
    assert_ref_parity(pair)


@UNIMPLEMENTED
def test_git_colocation_enable_then_disable(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "colocation", "enable"])
    pair.op(jj=["git", "colocation", "disable"])
    pair.assert_parity()
    assert_ref_parity(pair)


def test_bookmark_track_and_untrack_a_remote_bookmark(pair: RepoPair) -> None:
    """A fetched bookmark starts untracked; tracking it makes the local
    name follow the remote one."""
    base = Path(tempfile.mkdtemp())
    try:
        remote = _make_bare_remote(base)
        pair.init()
        pair.op(jj=["git", "remote", "add", "origin", str(remote)])
        pair.op(jj=["git", "fetch"])
        pair.op(jj=["bookmark", "untrack", "main@origin"])
        pair.assert_parity()
        pair.op(jj=["bookmark", "track", "main@origin"])
        pair.assert_parity()
    finally:
        shutil.rmtree(str(base), ignore_errors=True)


def test_bookmark_advance_moves_to_the_working_copy_parent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "advance", "main"])
    pair.assert_parity()


# -- global options -----------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--no-pager"],
        ["--no-pager", "status"],
        ["log", "--color", "never"],
        ["log", "--color=never"],
        ["status", "--quiet"],
        ["describe", "--no-pager", "-m", "renamed"],
    ],
    ids=lambda a: "_".join(a).replace("-", ""),
)
def test_display_only_global_options_are_accepted(pair: RepoPair, argv) -> None:
    """jj takes its global options anywhere on the command line. These
    four change only what is printed, so both sides must accept them and
    end up with the same repository."""
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


# -- abandon and duplicate placement ------------------------------------


def test_abandon_retain_bookmarks(pair: RepoPair) -> None:
    """Without the flag jj deletes a bookmark on an abandoned commit;
    with it, the bookmark moves to the parent."""
    chain(pair)
    pair.op(jj=["abandon", "--retain-bookmarks", rev("one")])
    pair.assert_parity()


def test_abandon_restore_descendants(pair: RepoPair) -> None:
    """The descendants keep their trees verbatim; a plain abandon would
    replay each one's diff against its new parent instead."""
    chain(pair)
    pair.op(jj=["abandon", "--restore-descendants", rev("one")])
    pair.assert_parity()


def test_abandon_restore_descendants_with_a_conflicting_change(
    pair: RepoPair,
) -> None:
    """Where a rebase would have to merge, reparenting simply keeps the
    child's own content -- so the two modes give different trees."""
    pair.init()
    pair.op(files={"a.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"a.txt": b"one\n"}, jj=["status"])
    pair.op(jj=["new", "-m", "two"])
    pair.op(files={"a.txt": b"two\n"}, jj=["status"])
    pair.op(jj=["abandon", "--restore-descendants", rev("one")])
    pair.assert_parity()


def test_duplicate_onto_another_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("two"), "--onto", rev("base")])
    pair.assert_parity()


def test_duplicate_insert_after(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("two"), "--insert-after", rev("base")])
    pair.assert_parity()


def test_duplicate_insert_before(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("base"), "--insert-before", rev("two")])
    pair.assert_parity()


# -- util ---------------------------------------------------------------


def test_util_gc_leaves_the_repo_alone(pair: RepoPair) -> None:
    """The default keeps everything written in the last two weeks, so a
    fresh repo loses nothing."""
    chain(pair)
    pair.op(jj=["util", "gc"])
    pair.assert_parity()


def test_util_gc_expire_now(pair: RepoPair) -> None:
    """`--expire=now` drops the grace period, so the sweep runs for real.

    What it collects is unreachable by definition, so this cannot claim
    the objects went -- `_extract_repo` only sees visible ones. The claim
    is the one the op-read family makes: both sides exit 0 and the
    visible repository is untouched."""
    chain(pair)
    pair.op(jj=["util", "gc", "--expire", "now"])
    pair.assert_parity()


def test_util_backend_name(pair: RepoPair) -> None:
    """Both repos are Git-backed, so both print the same name."""
    chain(pair)
    pair.op(jj=["util", "backend", "name"])
    pair.assert_parity()


def test_util_exec_runs_a_command(pair: RepoPair) -> None:
    """`util exec` does not snapshot, so a dirty working copy stays
    dirty on both sides."""
    chain(pair)
    pair.op(files={"unsnapshotted.txt": b"dirty\n"},
            jj=["util", "exec", "--", sys.executable, "-c", "pass"])
    pair.assert_parity()


def test_util_exec_propagates_the_exit_status(pair: RepoPair) -> None:
    """jj exits with the child's own status, so a failure is not jj's."""
    chain(pair)
    pair.op(jj=["util", "exec", "--", sys.executable, "-c",
                "raise SystemExit(3)"],
            may_fail=True)
    pair.assert_parity()


def test_util_snapshot_with_a_dirty_working_copy(pair: RepoPair) -> None:
    """A changed file makes the snapshot real on both sides."""
    chain(pair)
    pair.op(files={"late.txt": b"late\n"}, jj=["util", "snapshot"])
    pair.assert_parity()


def test_util_snapshot_with_a_clean_working_copy(pair: RepoPair) -> None:
    """Nothing moved, so nothing is written and no operation is made."""
    chain(pair)
    pair.op(jj=["util", "snapshot"])
    pair.assert_parity()


def test_util_gc_rejects_other_expire_values(pair: RepoPair) -> None:
    """jj accepts only the literal `now`."""
    chain(pair)
    pair.op(jj=["util", "gc", "--expire", "1h"], may_fail=True)
    pair.assert_parity()


# -- commands jj has and pyjj-cli does not yet ---------------------------
#
# Every one of these runs clean through `jj` and fails through pyjj-cli.
# They are the executable half of the coverage matrix in AGENTS.md: the
# xfail is strict, so the day a command lands, its scenario stops being
# an expected failure and the marker has to go.
#
# Not listed here, and excluded on purpose:
#   arrange       an interactive TUI, so there is no argv to compare
#   gerrit        needs a Gerrit server
#   sparse edit   opens the editor on both sides
#   bench, debug  hidden developer commands
#   hunk,         pyjj-cli's own commands; jj has no such subcommand, so
#   templates     there is nothing to run on the other side
#   op integrate  needs an operation created concurrently elsewhere, and
#                 this harness runs strictly one operation at a time
#   workspace     has to run inside the stale workspace, and `op()` always
#   update-stale  runs with the primary repo as cwd and prepends its own
#                 `-R`; jj rejects a second one


UNIMPLEMENTED_ARGV = [
    ["config", "gc"],
    ["log", "--stat"],
    ["run", "-r", rev("one"), "true"],
    ["util", "config-schema"],
]


@UNIMPLEMENTED
@pytest.mark.parametrize("argv", UNIMPLEMENTED_ARGV, ids=lambda a: "_".join(a)[:40])
def test_unimplemented_jj_command(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


def test_sign_without_a_backend_must_fail(pair: RepoPair) -> None:
    """Signing with no backend configured would rewrite the commit and
    attach nothing, so both sides must refuse and change nothing."""
    chain(pair)
    pair.op(jj=["sign", "-r", rev("one")], may_fail=True)
    pair.assert_parity()


# -- simplify-parents ---------------------------------------------------


def redundant_merge(pair: RepoPair) -> None:
    """`two` has both `one` and `base` as parents, and `base` is already
    an ancestor of `one` -- so the edge to `base` says nothing."""
    pair.init()
    pair.op(files={"base.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"one.txt": b"one\n"}, jj=["status"])
    pair.op(jj=["new", rev("one"), rev("base"), "-m", "two"])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"])


def test_simplify_parents_drops_the_redundant_edge(pair: RepoPair) -> None:
    redundant_merge(pair)
    pair.op(jj=["simplify-parents", "-r", rev("two")])
    pair.assert_parity()


def test_simplify_parents_by_source(pair: RepoPair) -> None:
    redundant_merge(pair)
    pair.op(jj=["simplify-parents", "-s", rev("base")])
    pair.assert_parity()


def test_simplify_parents_leaves_a_real_merge_alone(pair: RepoPair) -> None:
    """Neither parent of a genuine merge reaches the other, so nothing
    is dropped."""
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(files={"side.txt": b"side\n"}, jj=["status"])
    pair.op(jj=["new", rev("two"), rev("side"), "-m", "merge"])
    pair.op(jj=["simplify-parents", "-r", rev("merge")])
    pair.assert_parity()


def test_squash_keep_emptied_leaves_the_source_behind(pair: RepoPair) -> None:
    """Squashing everything out of a revision empties it, and jj abandons
    it -- unless asked not to."""
    chain(pair)
    pair.op(jj=["squash", "--keep-emptied", "-u"])
    pair.assert_parity()



def test_unsign_an_unsigned_commit_changes_nothing(pair: RepoPair) -> None:
    """No signature to remove, so both sides must leave the commit alone
    rather than rewriting it."""
    chain(pair)
    pair.op(jj=["unsign", "-r", rev("one")])
    pair.assert_parity()


def test_unsign_the_whole_chain_changes_nothing(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["unsign", "-r", "mutable()"])
    pair.assert_parity()


# -- metaedit -----------------------------------------------------------


def test_metaedit_sets_the_author(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--author", "Bob <bob@example.com>"])
    pair.assert_parity()


def test_metaedit_update_author(pair: RepoPair) -> None:
    """Name and email move to the configured user; the date does not."""
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--update-author"])
    pair.assert_parity()


def test_metaedit_update_author_timestamp(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--update-author-timestamp"])
    pair.assert_parity()


def test_metaedit_update_change_id(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--update-change-id"])
    pair.assert_parity()


def test_metaedit_message(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "-m", "renamed"])
    pair.assert_parity()


def test_metaedit_force_rewrite(pair: RepoPair) -> None:
    """`--force-rewrite` rewrites a commit no other flag would touch."""
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--force-rewrite"])
    pair.assert_parity()


def test_metaedit_force_rewrite_with_a_new_committer(pair: RepoPair) -> None:
    """The documented use: restamp the committer, nothing else."""
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "--force-rewrite",
                "--update-author"])
    pair.assert_parity()


def test_metaedit_several_revisions(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"), "-r", rev("two"),
                "--author", "Bob <bob@example.com>"])
    pair.assert_parity()


# -- parallelize --------------------------------------------------------


def test_parallelize_a_two_commit_chain(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["parallelize", rev("one"), rev("two")])
    pair.assert_parity()


def test_parallelize_leaves_a_follower_on_both(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", "-m", "three"])
    pair.op(files={"three.txt": b"three\n"}, jj=["status"])
    pair.op(jj=["parallelize", rev("one"), rev("two")])
    pair.assert_parity()


# -- repo-level config --------------------------------------------------
#
# Repo config lives OUTSIDE the repository, under
# `$XDG_CONFIG_HOME/jj/repos/<id>/`, so the harness never sees the file
# itself. What it sees is the effect: a commit written afterwards
# carries the configured author.


def test_config_set_repo_changes_later_commits(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "set", "--repo", "user.name", "Bob"])
    pair.op(jj=["new", "-m", "after"])
    pair.assert_parity()


def test_config_set_then_unset_restores_the_author(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "set", "--repo", "user.email", "bob@example.com"])
    pair.op(jj=["config", "unset", "--repo", "user.email"])
    pair.op(jj=["new", "-m", "after"])
    pair.assert_parity()


def test_config_unset_a_missing_key_fails_on_both(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "unset", "--repo", "user.name"], may_fail=True)
    pair.assert_parity()


@pytest.mark.parametrize(
    "argv",
    [
        ["config", "list"],
        ["config", "list", "--repo"],
        ["config", "path", "--repo"],
        ["config", "path", "--user"],
    ],
    ids=lambda a: "_".join(a).replace("-", ""),
)
def test_config_read_only_command(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=["config", "set", "--repo", "user.name", "Bob"])
    pair.op(jj=argv)
    pair.assert_parity()


def test_show_with_the_revision_flag(pair: RepoPair) -> None:
    """jj takes show's revisions positionally and accepts `-r` too."""
    chain(pair)
    pair.op(jj=["show", "-r", rev("one")])
    pair.assert_parity()


def test_help_prints_and_changes_nothing(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["help"])
    pair.assert_parity()


def test_help_for_one_command(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["help", "describe"])
    pair.assert_parity()


def test_metaedit_author_timestamp(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["metaedit", "-r", rev("one"),
                "--author-timestamp", "2011-12-13T14:15:16+00:00"])
    pair.assert_parity()


# -- interdiff and split --parallel -------------------------------------


def test_interdiff_between_two_revisions(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["interdiff", "--from", rev("base"), "--to", rev("one")])
    pair.assert_parity()


def test_interdiff_with_only_from(pair: RepoPair) -> None:
    """One of --from/--to is enough; the other defaults to `@`."""
    chain(pair)
    pair.op(jj=["interdiff", "--from", rev("one")])
    pair.assert_parity()


def test_interdiff_needs_from_or_to(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["interdiff"], may_fail=True)
    pair.assert_parity()


def test_split_parallel_makes_siblings(pair: RepoPair) -> None:
    """`--parallel` puts the two halves side by side, so the second one
    hangs from the original's parents and loses the first one's changes."""
    chain(pair)
    pair.op(jj=["split", "--parallel", "two.txt", "-m", "half"])
    pair.assert_parity()


def test_split_parallel_with_a_descendant(pair: RepoPair) -> None:
    """A commit below the split point ends up on both halves."""
    chain(pair)
    pair.op(jj=["new", "-m", "three"])
    pair.op(files={"three.txt": b"three\n"}, jj=["status"])
    pair.op(jj=["split", "--parallel", "-r", rev("two"), "two.txt", "-m", "half"])
    pair.assert_parity()


# -- op revert ----------------------------------------------------------
#
# Reverting is not restoring: `op restore` makes the view *be* a past
# view and drops everything after it, while `op revert` merges one
# operation back out and keeps the rest.


def test_op_revert_the_last_operation(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["op", "revert"])
    pair.assert_parity()


def test_op_revert_an_earlier_operation_keeps_later_ones(pair: RepoPair) -> None:
    """The bookmark move is reverted; the commit made after it stays."""
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.op(jj=["new", "-m", "three"])
    pair.op(
        jj=["op", "revert", pair.op_id("cli", 1)],
        py=["op", "revert", pair.op_id("py", 1)],
    )
    pair.assert_parity()


def test_op_revert_a_describe(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["op", "revert"])
    pair.assert_parity()
