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

import re

import pytest

from parity_harness import DRIVER, RepoPair, make_bare_remote

pytestmark = pytest.mark.skipif(
    shutil.which(os.environ.get("PYJJ_PARITY_JJ", "jj")) is None,
    reason="jj binary not available",
)


def rev(name: str) -> str:
    return f'description(glob:"{name}*")'


def chain(pair: RepoPair) -> None:
    """base <- one <- two, with base.txt/one.txt/two.txt and bookmark main
    on 'one' -- the shared prefix most scenarios start from.

    Restored from a copy built once per session rather than replayed;
    `conftest.build_chain` is the definition. Replaying costs ten CLI
    runs, and 164 tests start here.
    """
    template, step = pair.chain_template
    pair.load_template(template, step)


def test_init_only(pair: RepoPair) -> None:
    pair.init()
    pair.assert_parity()


def test_describe_and_commit_chain(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_parity()


@pytest.mark.covers("squash", "-r", "--use-destination-message")
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


@pytest.mark.covers("commit", "-m")
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


@pytest.mark.covers("describe", "--stdin")
def test_describe_stdin_description(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"a\n"}, jj=["describe", "--stdin"], stdin="from stdin\n")
    pair.assert_parity()


@pytest.mark.covers("restore")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("split", "-m")
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


@pytest.mark.covers("undo")
def test_undo_bookmark_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.op(jj=["undo"])
    pair.assert_parity()


@pytest.mark.covers("redo")
@pytest.mark.covers("undo")
def test_undo_then_redo(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "set", "main", "-r", rev("two")])
    pair.op(jj=["undo"])
    pair.op(jj=["redo"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("undo")
def test_undo_describe(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.assert_parity()


@pytest.mark.covers("bookmark create")
@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("undo")
def test_undo_twice(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "create", "extra"])
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.op(jj=["undo"])
    pair.assert_parity()


@pytest.mark.covers("bookmark create")
@pytest.mark.covers("new", "-m")
def test_op_restore_skips_last_operation(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "create", "extra"])
    # Depth 1 = the state before the last logical operation: the new
    # empty commit disappears, the bookmark creation stays.
    pair.op(jj=["new", "-m", "transient"])
    pair.op_restore(1)
    pair.assert_parity()


@pytest.mark.covers("new", "-m")
def test_op_restore_across_wc_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["new", "-m", "later"])
    # Back two ops lands on the pre-chain-head working copy; both sides
    # must check the on-disk working copy back out to it.
    pair.op_restore(2)
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("undo")
def test_undo_across_file_write(pair: RepoPair) -> None:
    chain(pair)
    # The dirty-wc describe emits "snapshot working copy" then "describe
    # commit" on both sides; one undo removes only the describe.
    pair.op(files={"two.txt": b"changed\n"}, jj=["describe", "-m", "renamed"])
    pair.op(jj=["undo"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("undo")
def test_undo_twice_past_describe_onto_snapshot(pair: RepoPair) -> None:
    chain(pair)
    pair.op(files={"two.txt": b"changed\n"}, jj=["describe", "-m", "renamed"])
    pair.op(jj=["bookmark", "set", "main", "-r", rev("renamed")])
    pair.op(jj=["undo"])
    # The second undo removes the describe; the standalone snapshot op is
    # now head on both sides.
    pair.op(jj=["undo"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("undo")
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


@pytest.mark.covers("resolve", "-l")
def test_resolve_list_shows_conflicts(pair: RepoPair) -> None:
    conflict_pair(pair)
    pair.op(jj=["resolve", "-l"])
    # --list must not touch state at all.
    pair.assert_parity()


@pytest.mark.covers("resolve")
def test_resolve_no_conflicts_is_an_error(pair: RepoPair) -> None:
    chain(pair)
    rc = pair.op(jj=["resolve"], may_fail=True)
    assert rc != 0
    pair.assert_parity()


@pytest.mark.covers("resolve", "--tool")
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


@pytest.mark.covers("resolve", "--tool")
def test_resolve_pick_left_resolves_fully(pair: RepoPair) -> None:
    multi_hunk_conflict(pair)
    # A whole-side pick collapses every region of both hunks at once.
    pair.op(
        jj=["resolve", "--tool", "parity-merge"],
        merge_spec={"op": "pick_left"},
    )
    pair.assert_parity()


@pytest.mark.covers("resolve", "--tool")
def test_resolve_verbatim_output_is_taken_as_is(pair: RepoPair) -> None:
    conflict_pair(pair)
    # parity-write runs without merge-tool-edits-conflict-markers: $output
    # starts empty and its final bytes become the resolved file verbatim.
    pair.op(
        jj=["resolve", "--tool", "parity-write"],
        merge_spec={"op": "pick_right"},
    )
    pair.assert_parity()


@pytest.mark.covers("resolve", "--tool")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
@pytest.mark.covers("resolve", "--tool")
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


@pytest.mark.covers("bookmark create")
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


@pytest.mark.covers("squash", "-r", "-m")
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


@pytest.mark.covers("describe")
def test_describe_via_editor(pair: RepoPair) -> None:
    pair.init()
    pair.op(
        files={"a.txt": b"a\n"},
        jj=["describe"],
        editor_spec={"op": "set", "value": "edited description\n"},
    )
    pair.assert_parity()


@pytest.mark.covers("describe")
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


@pytest.mark.covers("commit")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("split")
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


@pytest.mark.covers("split", "--tool", "-m")
def test_split_via_diff_tool_selects_whole_files(pair: RepoPair) -> None:
    two_file_change(pair)
    pair.op(
        jj=["split", "--tool", "parity-diff", "-m", "first"],
        diff_spec={"op": "keep", "paths": ["one.txt"]},
    )
    pair.assert_parity()


@pytest.mark.covers("split", "--tool", "-m")
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


@pytest.mark.covers("split", "--tool", "-m")
def test_split_diff_tool_dropped_file_stays_in_remainder(pair: RepoPair) -> None:
    two_file_change(pair)
    pair.op(
        jj=["split", "--tool", "parity-diff", "-m", "first"],
        diff_spec={"op": "drop", "paths": ["two.txt"]},
    )
    pair.assert_parity()


@pytest.mark.covers("diffedit", "--tool")
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

@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new")
def test_absorb_moves_change_into_parent(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"line1\nline2\nline3\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"line1\nLINE2-MODIFIED\nline3\n"}, jj=["status"])
    pair.op(jj=["absorb", "--from", "@", "--into", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("absorb")
@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new")
def test_absorb_default_mutable_destination(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"line1\nline2\nline3\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"line1\nLINE2-MODIFIED\nline3\n"}, jj=["status"])
    pair.op(jj=["absorb"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new")
def test_absorb_with_path_filter(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"a.txt": b"a1\n", "b.txt": b"b1\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"a1-changed\n", "b.txt": b"b1-changed\n"}, jj=["status"])
    pair.op(jj=["absorb", "--into", rev("base"), "a.txt"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("fix")
@pytest.mark.covers("new")
def test_fix_basic(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"hello\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"hello world\n"}, jj=["status"])
    pair.op(jj=["fix"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("fix")
@pytest.mark.covers("new")
def test_fix_with_path_filter(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"a\n", "b.txt": b"b\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new"])
    pair.op(files={"a.txt": b"a changed\n", "b.txt": b"b changed\n"}, jj=["status"])
    pair.op(jj=["fix", "a.txt"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
def test_fix_with_source_filter(pair: RepoPair) -> None:
    _add_fix_tool(pair)
    pair.init()
    pair.op(files={"a.txt": b"hello\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "child"])
    pair.op(files={"a.txt": b"hello world\n"}, jj=["status"])
    pair.op(jj=["fix", "-s", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new")
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

@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
@pytest.mark.covers("revert", "-r", "--onto")
def test_revert_single_onto_parent(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"hello\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"hello\nworld\n"}, jj=["status"])
    pair.op(jj=["revert", "-r", rev("B"), "--onto", rev("A")])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
def test_revert_onto_self(pair: RepoPair) -> None:
    pair.init()
    pair.op(files={"file.txt": b"hello\n"}, jj=["describe", "-m", "A"])
    pair.op(jj=["new", "-m", "B"])
    pair.op(files={"file.txt": b"hello\nworld\n"}, jj=["status"])
    pair.op(jj=["revert", "-r", rev("B"), "--onto", rev("B")])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
@pytest.mark.covers("revert", "-r", "--onto")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
@pytest.mark.covers("revert", "-r", "--insert-after")
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

# The helper lives in the harness now, so the corpus fixtures can build
# a remote too. Read-only listings that mention one need a repository
# that has one, and no catalogue entry conjures it.
_make_bare_remote = make_bare_remote


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


@pytest.mark.covers("git fetch")
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


@pytest.mark.covers("bookmark create")
@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("git fetch")
@pytest.mark.covers("git push", "--remote", "-b")
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


@pytest.mark.covers("git remote add")
@pytest.mark.covers("git remote remove")
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


# -- run ----------------------------------------------------------------
#
# `jj run` checks each revision out into a scratch slot under
# `.jj/run/default/`, runs a command there, and writes the result back.
# The command itself lives outside both repos, for the same reason the
# bisect predicate does: every slot holds a different tree, so a script
# stored in the working copy would not survive the first checkout.


def run_script(tmp_path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text(body)
    return str(script)


def test_run_command_that_changes_nothing(pair: RepoPair, tmp_path) -> None:
    """A command that touches no file must leave both repos alone."""
    chain(pair)
    script = run_script(tmp_path, "noop.py", "pass\n")
    pair.op(jj=["run", "-r", rev("one"), sys.executable, script])
    pair.assert_parity()


def test_run_no_op_writes_no_operation(pair: RepoPair, tmp_path) -> None:
    """A command that changes nothing must not leave an operation
    behind. jj's `finish()` returns early on an empty transaction, so
    the operation log does not grow. `op_restore` addresses operations
    by depth per side, so a side that wrote one extra restores to a
    different state and the repos diverge here."""
    chain(pair)
    script = run_script(tmp_path, "noop.py", "pass\n")
    pair.op(jj=["run", "-r", rev("one"), sys.executable, script])
    pair.op_restore(1)
    pair.assert_parity()


def test_run_rewrites_and_propagates_to_descendants(pair: RepoPair, tmp_path) -> None:
    """The real claim: a command that edits a file rewrites its revision
    AND every descendant, so both sides must reproduce the same commit
    ids all the way down the chain."""
    chain(pair)
    script = run_script(
        tmp_path, "append.py",
        "import pathlib\n"
        "p = pathlib.Path('base.txt')\n"
        "p.write_bytes(p.read_bytes() + b'ran\\n')\n",
    )
    pair.op(jj=["run", "-r", rev("one"), sys.executable, script])
    pair.assert_parity()


def test_run_adding_a_file_across_the_whole_chain(pair: RepoPair, tmp_path) -> None:
    """No `-r` means the `revsets.run` default, `reachable(@, mutable())`
    -- every mutable revision, each in its own slot, one after another."""
    chain(pair)
    script = run_script(
        tmp_path, "add.py",
        "import pathlib\n"
        "pathlib.Path('added.txt').write_bytes(b'added\\n')\n",
    )
    pair.op(jj=["run", sys.executable, script])
    pair.assert_parity()


def test_run_restore_descendants_keeps_their_content(pair: RepoPair, tmp_path) -> None:
    """`--restore-descendants` reparents the descendants instead of
    rebasing them, so their trees do not move -- a different set of
    commit ids from the default, and both sides must pick the same one."""
    chain(pair)
    script = run_script(
        tmp_path, "append.py",
        "import pathlib\n"
        "p = pathlib.Path('base.txt')\n"
        "p.write_bytes(p.read_bytes() + b'ran\\n')\n",
    )
    pair.op(jj=["run", "--restore-descendants", "-r", rev("base"),
                sys.executable, script])
    pair.assert_parity()


def test_run_failing_command_writes_nothing(pair: RepoPair, tmp_path) -> None:
    """A nonzero exit aborts the whole run. Both sides must fail, and
    neither may keep the edit the command already made."""
    chain(pair)
    script = run_script(
        tmp_path, "fail.py",
        "import pathlib, sys\n"
        "pathlib.Path('base.txt').write_bytes(b'ruined\\n')\n"
        "sys.exit(1)\n",
    )
    pair.op(jj=["run", "-r", rev("one"), sys.executable, script],
            may_fail=True)
    pair.assert_parity()


def test_run_clean_slot_each_time(pair: RepoPair, tmp_path) -> None:
    """`--clean` wipes each slot before the checkout, so nothing a
    previous revision left behind can leak into the next one."""
    chain(pair)
    script = run_script(
        tmp_path, "add.py",
        "import pathlib\n"
        "pathlib.Path('added.txt').write_bytes(b'added\\n')\n",
    )
    pair.op(jj=["run", "--clean", sys.executable, script])
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


@pytest.mark.covers("bookmark delete")
def test_bookmark_delete(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "delete", "main"])
    pair.assert_parity()


@pytest.mark.covers("bookmark forget")
def test_bookmark_forget(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "forget", "main"])
    pair.assert_parity()


@pytest.mark.covers("bookmark rename")
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


@pytest.mark.covers("rebase", "-b")
def test_rebase_branch_onto_grandparent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-b", rev("two"), "-d", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("rebase", "-r", "--insert-after")
def test_rebase_insert_after(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-r", rev("two"), "--insert-after", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("rebase", "-r", "--insert-before")
def test_rebase_insert_before(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["rebase", "-r", rev("two"), "--insert-before", rev("one")])
    pair.assert_parity()


# -- rebase's rebase options --------------------------------------------
#
# These three reach `RebaseOptions`, which the binding used to leave at
# its default. The scenarios are jj's own, from
# `cli/tests/test_rebase_command.rs`: a graph that shows the flag off
# is not a graph that shows it on.


def test_rebase_defaults_to_the_whole_branch(pair: RepoPair) -> None:
    """With no `-r`, `-s` or `-b`, jj rebases `-b @`: the roots of @'s
    branch relative to the destination, and everything under them. `-s @`
    would move only @ itself, which is a different graph."""
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(jj=["edit", rev("two")])
    pair.op(jj=["rebase", "-d", rev("side")])
    pair.assert_parity()


@pytest.mark.covers("rebase", "--skip-emptied")
def test_rebase_skip_emptied(pair: RepoPair) -> None:
    """A commit the rebase newly empties is abandoned. One that was
    already empty is kept, which is the whole distinction."""
    pair.init()
    pair.op(files={"file.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "target"])
    pair.op(files={"file.txt": b"target\n"}, jj=["status"])
    pair.op(jj=["new", rev("base"), "-m", "becomes empty"])
    pair.op(jj=["restore", "--from", rev("target")])
    pair.op(jj=["new", "-m", "emptyone"])
    pair.op(jj=["new", "-m", "emptytwo"])
    pair.op(jj=["rebase", "-d", rev("target"), "--skip-emptied"])
    pair.assert_parity()


@pytest.mark.covers("rebase", "--simplify-parents")
def test_rebase_simplify_parents(pair: RepoPair) -> None:
    """A merge whose parents are ancestors of each other loses the
    redundant one."""
    pair.init()
    pair.op(files={"root.txt": b"root\n"}, jj=["describe", "-m", "aroot"])
    pair.op(jj=["new", "-m", "aone"])
    pair.op(files={"one.txt": b"one\n"}, jj=["status"])
    pair.op(jj=["new", "-m", "atwo"])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"])
    pair.op(jj=["new", rev("atwo"), rev("aone"), "-m", "athree"])
    pair.op(files={"three.txt": b"three\n"}, jj=["status"])
    pair.op(jj=["new", "root()", "-m", "side"])
    pair.op(files={"side.txt": b"side\n"}, jj=["status"])
    pair.op(jj=["rebase", "-s", rev("aroot"), "-o", rev("side"),
                "--simplify-parents"])
    pair.assert_parity()


def divergence(pair: RepoPair) -> None:
    """A repository holding two versions of one change.

    `at_operation` resurrects the commit the rebase rewrote, so the
    change id now names two visible commits. This is jj's own setup, from
    `test_rebase_skip_duplicate_divergent`.
    """
    pair.init()
    pair.op(files={"file1": b"initial\n"}, jj=["describe", "-m", "aroot"])
    pair.op(jj=["new", "-m", "btwo"])
    pair.op(files={"file1": b"initial\nb\n"}, jj=["status"])
    pair.op(jj=["new", rev("aroot"), "-m", "cee"])
    pair.op(files={"file2": b"c\n"}, jj=["status"])
    pair.op(jj=["rebase", "-r", rev("btwo"), "-o", rev("cee")])
    pair.op(jj=["bookmark", "create", "bone",
                "-r", f'at_operation(@-, {rev("btwo")})'])
    pair.op(jj=["new", "bone", "-m", "dee"])
    pair.op(files={"file3": b"d\n"}, jj=["status"])


def test_rebase_abandons_a_duplicate_divergent_commit(pair: RepoPair) -> None:
    """The default. One of the two versions is already in the
    destination with identical contents, so the rebase drops it."""
    divergence(pair)
    pair.op(jj=["rebase", "-r", f'{rev("cee")}::', "-o", rev("dee")])
    pair.assert_parity()


@pytest.mark.covers("rebase", "--keep-divergent")
def test_rebase_keeps_a_divergent_commit_when_asked(pair: RepoPair) -> None:
    """With the flag, both versions survive the rebase."""
    divergence(pair)
    pair.op(jj=["rebase", "-s", rev("cee"), "-o", rev("dee"),
                "--keep-divergent"])
    pair.assert_parity()


@pytest.mark.covers("duplicate", "-r")
def test_duplicate_by_the_hidden_revision_flag(pair: RepoPair) -> None:
    """The revisions are positional here. jj hides a `-r` beside them
    for the reader who types it out of habit."""
    chain(pair)
    pair.op(jj=["duplicate", "-r", rev("one")])
    pair.assert_parity()


# -- the other spellings of the placement flags -------------------------
#
# jj gives each placement option several names: `-o` is also `--onto`,
# `-d` and `--destination`; `-A` is also `--after`; `-B` is also
# `--before`. Every spelling is its own item on the checklist, because
# pyjj-cli accepted two of three for `split` until the surface
# comparison found the third.

REBASE_SPELLING_ARGV = [
    ["rebase", "--revision", rev("two"), "--destination", rev("base")],
    ["rebase", "--revisions", rev("two"), "--destination", rev("base")],
    ["rebase", "--branch", rev("two"), "--onto", rev("base")],
    ["rebase", "--source", rev("two"), "-o", rev("base")],
    ["rebase", "-r", rev("two"), "--after", rev("base")],
    ["rebase", "-r", rev("two"), "--before", rev("one")],
]


# `--revisions` is not on the checklist: `markdown-help` hides it, the
# same way it hides `jj squash -d`. The row still types it, because jj
# accepts it and so must pyjj-cli.
@pytest.mark.covers("rebase", "--revision")
@pytest.mark.covers("rebase", "--destination", "--branch")
@pytest.mark.covers("rebase", "--source", "--onto", "-o")
@pytest.mark.covers("rebase", "--after", "--before")
@pytest.mark.parametrize("argv", REBASE_SPELLING_ARGV,
                         ids=lambda a: a[1] + "_" + a[3])
def test_rebase_by_each_spelling(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


REVERT_SPELLING_ARGV = [
    ["revert", "--revision", rev("one"), "-o", rev("base")],
    ["revert", "-r", rev("one"), "--destination", rev("base")],
    ["revert", "-r", rev("one"), "--after", rev("base")],
    ["revert", "-r", rev("one"), "--before", rev("two")],
    ["revert", "-r", rev("one"), "--insert-before", rev("two")],
]


@pytest.mark.covers("revert", "--revision", "--destination", "-o")
@pytest.mark.covers("revert", "--after", "--before", "--insert-before")
@pytest.mark.parametrize("argv", REVERT_SPELLING_ARGV,
                         ids=lambda a: a[1] + "_" + a[3])
def test_revert_by_each_spelling(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


DUPLICATE_SPELLING_ARGV = [
    ["duplicate", rev("one"), "--destination", rev("base")],
    ["duplicate", rev("one"), "-o", rev("base")],
    ["duplicate", rev("one"), "--after", rev("base")],
    ["duplicate", rev("one"), "--before", rev("two")],
]


@pytest.mark.covers("duplicate", "--destination", "-o")
@pytest.mark.covers("duplicate", "--after", "--before")
@pytest.mark.parametrize("argv", DUPLICATE_SPELLING_ARGV,
                         ids=lambda a: a[2])
def test_duplicate_by_each_spelling(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


# -- squash and restore variants ----------------------------------------


@pytest.mark.covers("squash", "-u")
def test_squash_working_copy_into_parent(pair: RepoPair) -> None:
    """`-u` is `--use-destination-message`: no editor, so no prompt."""
    chain(pair)
    pair.op(jj=["squash", "-u"])
    pair.assert_parity()


def test_squash_from_into_named_revisions(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "--from", rev("two"), "--into", rev("one"), "-u"])
    pair.assert_parity()


@pytest.mark.covers("squash", "-f")
def test_squash_from_defaults_to_the_working_copy(pair: RepoPair) -> None:
    """`--into` defaults to `@`, not to the source's own parent. Only the
    plain `-r` form squashes into the parent."""
    chain(pair)
    pair.op(jj=["squash", "-f", rev("one"), "-u"])
    pair.assert_parity()


@pytest.mark.covers("squash", "--to")
def test_squash_to_is_another_spelling_of_into(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "--from", rev("two"), "--to", rev("one"), "-u"])
    pair.assert_parity()


@pytest.mark.covers("squash", "-t")
def test_squash_into_short_spelling(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "-f", rev("two"), "-t", rev("one"), "-u"])
    pair.assert_parity()


@pytest.mark.covers("squash", "-k")
def test_squash_keeping_the_emptied_source(pair: RepoPair) -> None:
    """Without `-k` the source is abandoned once it holds nothing."""
    chain(pair)
    pair.op(jj=["squash", "-k", "-u"])
    pair.assert_parity()


@pytest.mark.covers("squash", "--revision", "--message")
def test_squash_with_the_long_flag_spellings(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["squash", "--revision", rev("one"),
                "--message", "explicit message"])
    pair.assert_parity()


@pytest.mark.covers("squash", "--tool")
def test_squash_via_diff_tool_selects_whole_files(pair: RepoPair) -> None:
    """The tool edits a copy of the source's own diff. What the right
    side holds when it exits is what moves, so a file deleted there
    stays behind in the source."""
    two_file_change(pair)
    pair.op(jj=["squash", "--tool", "parity-diff", "-u"],
            diff_spec={"op": "keep", "paths": ["one.txt"]})
    pair.assert_parity()


@pytest.mark.covers("squash", "--tool")
def test_squash_diff_tool_partial_edit_is_verbatim(pair: RepoPair) -> None:
    """Editing a line inside the right directory moves that file with the
    edited bytes -- fidelity beyond whole-file selection."""
    two_file_change(pair)
    pair.op(jj=["squash", "--tool", "parity-diff", "-u"],
            diff_spec={"op": "edit",
                       "edits": [{"path": "one.txt",
                                  "find": "one", "replace": "one-edited"}]})
    pair.assert_parity()


@pytest.mark.covers("squash", "--tool")
def test_squash_diff_tool_selecting_nothing_fails(pair: RepoPair) -> None:
    """A selection that moves nothing is a mistake, not a no-op: the
    reader was asked to choose and chose none."""
    two_file_change(pair)
    assert pair.op(jj=["squash", "--tool", "parity-diff", "-u"],
                   diff_spec={"op": "drop", "paths": ["one.txt", "two.txt"]},
                   may_fail=True) != 0
    pair.assert_parity()


@pytest.mark.covers("squash", "--editor")
def test_squash_editor_opens_over_an_explicit_message(pair: RepoPair) -> None:
    """`-m` normally means no editor. `--editor` opens one anyway, and
    what it writes is what the commit keeps."""
    chain(pair)
    pair.op(jj=["squash", "-r", rev("one"), "-m", "explicit", "--editor"],
            editor_spec={"op": "set", "value": "edited over the message\n"})
    pair.assert_parity()


@pytest.mark.covers("squash", "--editor")
def test_squash_editor_opens_over_the_destination_message(pair: RepoPair) -> None:
    """`-u` normally keeps the destination's description untouched."""
    chain(pair)
    pair.op(jj=["squash", "-r", rev("one"), "-u", "--editor"],
            editor_spec={"op": "set", "value": "edited\n"})
    pair.assert_parity()


# -- squash's experimental placement UI ----------------------------------
#
# `-o`, `-A` and `-B` squash into a commit that does not exist yet: jj
# creates an empty one at the named place, rebases whatever followed it,
# and squashes the source into that. The source is usually one of the
# commits the insertion rebases -- `@` sits below almost any insertion
# point -- so a scenario that inserted above `@` and then squashed the
# pre-rebase `@` would write a second version of it.

SQUASH_PLACEMENT_ARGV = [
    ["squash", "--onto", rev("base")],
    ["squash", "-o", rev("base")],
    ["squash", "--destination", rev("base")],
    ["squash", "-d", rev("base")],
    ["squash", "--insert-after", rev("base")],
    ["squash", "-A", rev("base")],
    ["squash", "--after", rev("base")],
    ["squash", "--insert-before", rev("one")],
    ["squash", "-B", rev("one")],
    ["squash", "--before", rev("one")],
]


@pytest.mark.covers("squash", "-o", "--onto", "--destination")
@pytest.mark.covers("squash", "-A", "--insert-after", "--after")
@pytest.mark.covers("squash", "-B", "--insert-before", "--before")
@pytest.mark.parametrize("argv", SQUASH_PLACEMENT_ARGV,
                         ids=lambda a: "_".join(a[:2]))
def test_squash_into_a_commit_it_creates(pair: RepoPair, argv) -> None:
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


@pytest.mark.covers("squash", "--onto", "-B")
def test_squash_placed_below_a_named_source(pair: RepoPair) -> None:
    """`--from` names the source outright, so the insertion point is not
    the working copy's own ancestry."""
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(files={"side.txt": b"side\n"}, jj=["status"])
    pair.op(jj=["squash", "--from", rev("side"), "--onto", rev("one")])
    pair.assert_parity()


SQUASH_REFUSED_ARGV = [
    ["squash", "-r", rev("one"), "--into", rev("base")],
    ["squash", "-r", rev("one"), "--from", rev("two")],
    ["squash", "--onto", rev("base"), "--into", rev("one")],
    ["squash", "-A", rev("base"), "--onto", rev("one")],
    ["squash", "-B", rev("two"), "--into", rev("one")],
    ["squash", "-m", "text", "--use-destination-message"],
]


@pytest.mark.parametrize("argv", SQUASH_REFUSED_ARGV,
                         ids=lambda a: "_".join(a[:4])[:40])
def test_squash_refuses_the_flag_pairs_jj_refuses(pair: RepoPair, argv) -> None:
    """`-r` names a commit and its parent, so nothing that names a
    destination fits beside it, and `-o` names the parents outright, so
    an insertion point does not."""
    chain(pair)
    assert pair.op(jj=argv, may_fail=True) != 0
    pair.assert_parity()


def test_restore_into_named_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["restore", "--into", rev("two"), "--from", rev("base")])
    pair.assert_parity()


# -- working-copy navigation --------------------------------------------


@pytest.mark.covers("prev")
def test_prev_moves_to_the_parent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["prev"])
    pair.assert_parity()


@pytest.mark.covers("prev", "--edit")
def test_prev_with_edit_moves_onto_the_parent(pair: RepoPair) -> None:
    """`--edit` moves onto the parent itself, one step less far back than
    the default, which lands a NEW commit below it."""
    chain(pair)
    pair.op(jj=["prev", "--edit"])
    pair.assert_parity()


@pytest.mark.covers("prev", "--edit")
def test_prev_with_an_offset(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["prev", "2", "--edit"])
    pair.assert_parity()


@pytest.mark.covers("next")
def test_next_moves_onto_the_sibling_line(pair: RepoPair) -> None:
    """`next` walks forward from `@`'s PARENT and skips `@` itself, so
    from a sibling branch it lands on the other line of development."""
    chain(pair)
    pair.op(jj=["new", rev("base"), "-m", "side"])
    pair.op(jj=["next"])
    pair.assert_parity()


@pytest.mark.covers("next", "--edit")
def test_next_with_edit_moves_onto_the_descendant(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["edit", rev("base")])
    pair.op(jj=["next", "--edit"])
    pair.assert_parity()


@pytest.mark.covers("next")
def test_next_without_a_descendant_fails_on_both(pair: RepoPair) -> None:
    """At the tip there is nothing to move to. Both sides must refuse,
    and neither may change the repository while refusing."""
    chain(pair)
    pair.op(jj=["next"], may_fail=True)
    pair.assert_parity()


@pytest.mark.covers("next")
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


@pytest.mark.covers("new", "--no-edit", "-m")
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


@pytest.mark.covers("file chmod")
def test_file_chmod_executable(pair: RepoPair) -> None:
    """The executable bit is part of the git tree, so a divergence here
    changes the commit id."""
    chain(pair)
    pair.op(jj=["file", "chmod", "x", "two.txt"])
    pair.assert_parity()


@pytest.mark.covers("file chmod")
def test_file_chmod_back_to_normal(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["file", "chmod", "x", "two.txt"])
    pair.op(jj=["file", "chmod", "n", "two.txt"])
    pair.assert_parity()


@pytest.mark.covers("file track")
def test_file_track_is_a_no_op_by_default(pair: RepoPair) -> None:
    """`snapshot.auto-track` defaults to `all()`, so tracking an already
    tracked path changes nothing."""
    chain(pair)
    pair.op(jj=["file", "track", "two.txt"])
    pair.assert_parity()


@pytest.mark.covers("file untrack")
def test_file_untrack_an_ignored_path(pair: RepoPair) -> None:
    """`file untrack` drops a path from the tree but leaves it on disk."""
    chain(pair)
    pair.op(files={".gitignore": b"two.txt\n"}, jj=["status"])
    pair.op(jj=["file", "untrack", "two.txt"])
    pair.assert_parity()
    for side in ("cli", "py"):
        assert pair.read_wc_file(side, "two.txt") == b"two\n"


@pytest.mark.covers("file untrack")
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


@pytest.mark.covers("sparse set", "--add", "--clear")
def test_sparse_set_narrows_the_working_copy(pair: RepoPair) -> None:
    """Narrowing removes paths from disk but not from the commit."""
    chain(pair)
    pair.op(jj=["sparse", "set", "--clear", "--add", "base.txt"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("sparse set", "--add", "--clear")
def test_sparse_set_then_edit_only_touches_the_visible_path(pair: RepoPair) -> None:
    """A snapshot taken through a narrowed working copy must not drop the
    paths that are no longer materialized."""
    chain(pair)
    pair.op(jj=["sparse", "set", "--clear", "--add", "base.txt"])
    pair.op(files={"base.txt": b"base edited\n"}, jj=["describe", "-m", "narrow"])
    pair.assert_parity()


@pytest.mark.covers("sparse reset")
@pytest.mark.covers("sparse set", "--add", "--clear")
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


@pytest.mark.covers("tag delete")
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


@pytest.mark.covers("workspace add", "--name")
def test_workspace_add(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "add", "--name", "second", "../second"])
    pair.assert_parity()


@pytest.mark.covers("workspace add", "--name")
@pytest.mark.covers("workspace forget")
def test_workspace_add_then_forget(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["workspace", "add", "--name", "second", "../second"])
    pair.op(jj=["workspace", "forget", "second"])
    pair.assert_parity()


@pytest.mark.covers("workspace rename")
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


@pytest.mark.covers("git export")
def test_git_export_writes_bookmarks_as_git_refs(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "export"])
    pair.assert_parity()
    assert_ref_parity(pair)
    assert any(name.startswith("refs/heads/main") for name in git_refs(pair, "cli"))


@pytest.mark.covers("git export")
@pytest.mark.covers("git import")
def test_git_import_after_export_is_a_no_op(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "export"])
    pair.op(jj=["git", "import"])
    pair.assert_parity()
    assert_ref_parity(pair)


@pytest.mark.covers("bookmark delete")
@pytest.mark.covers("git export")
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


@pytest.mark.covers("git colocation enable")
def test_git_colocation_enable(pair: RepoPair) -> None:
    """Colocation puts a real `.git` beside `.jj`, so git refs must match
    afterwards too.

    Both repos are colocated already -- that is what `git init` does
    now -- so this is the no-op path: both sides say so and change
    nothing. Converting a non-colocated repo is still unimplemented, and
    `test_git_colocation_enable_then_disable` still covers that.
    """
    chain(pair)
    pair.op(jj=["git", "colocation", "enable"])
    pair.assert_parity()
    assert_ref_parity(pair)


@pytest.mark.covers("git colocation disable")
@pytest.mark.covers("git colocation enable")
@UNIMPLEMENTED
def test_git_colocation_enable_then_disable(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["git", "colocation", "enable"])
    pair.op(jj=["git", "colocation", "disable"])
    pair.assert_parity()
    assert_ref_parity(pair)


@pytest.mark.covers("bookmark track")
@pytest.mark.covers("bookmark untrack")
@pytest.mark.covers("git fetch")
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


@pytest.mark.covers("bookmark advance")
def test_bookmark_advance_moves_to_the_working_copy_parent(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["bookmark", "advance", "main"])
    pair.assert_parity()


# -- global options -----------------------------------------------------


@pytest.mark.covers("describe", "-m")
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


@pytest.mark.covers("describe", "-m")
@pytest.mark.covers("new", "-m")
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


@pytest.mark.covers("duplicate", "--onto")
def test_duplicate_onto_another_revision(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("two"), "--onto", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("duplicate", "--insert-after")
def test_duplicate_insert_after(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("two"), "--insert-after", rev("base")])
    pair.assert_parity()


@pytest.mark.covers("duplicate", "--insert-before")
def test_duplicate_insert_before(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["duplicate", rev("base"), "--insert-before", rev("two")])
    pair.assert_parity()


# -- --stat ---------------------------------------------------------------


def test_log_stat(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["log", "--stat"])
    pair.assert_parity()


def test_log_stat_no_graph(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["log", "--stat", "--no-graph"])
    pair.assert_parity()


@pytest.mark.covers("describe", "-m")
def test_log_stat_over_a_binary_file(pair: RepoPair) -> None:
    """A NUL in the first bytes makes it binary, and it has no lines."""
    pair.init()
    pair.op(files={"a.bin": b"\x00\x01\x02"}, jj=["describe", "-m", "one"])
    pair.op(jj=["log", "--stat"])
    pair.assert_parity()


def test_diff_stat(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["diff", "--stat"])
    pair.assert_parity()


def test_diff_stat_from_and_to(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["diff", "--stat", "--from", rev("base"), "--to", rev("two")])
    pair.assert_parity()


def test_show_stat(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["show", "--stat", rev("one")])
    pair.assert_parity()


@pytest.mark.covers("config gc")
def test_config_gc_with_nothing_to_collect(pair: RepoPair) -> None:
    """Both repos still exist, so neither side has a leftover config."""
    chain(pair)
    pair.op(jj=["config", "gc"])
    pair.assert_parity()


# -- behaviour-changing global options -----------------------------------


def test_ignore_working_copy_skips_the_snapshot(pair: RepoPair) -> None:
    """The new file stays out of every commit: no snapshot, no operation.

    Without the flag, `status` would have absorbed it into `@`."""
    chain(pair)
    pair.op(files={"unsnapshotted.txt": b"dirty\n"},
            jj=["--ignore-working-copy", "status"])
    pair.assert_parity()


def test_ignore_working_copy_before_a_write(pair: RepoPair) -> None:
    """A write command must not snapshot either.

    This checks the first half only. The second -- not updating the
    working copy afterwards -- leaves the same bytes on disk here, so
    the harness cannot tell it apart."""
    chain(pair)
    pair.op(files={"unsnapshotted.txt": b"dirty\n"},
            jj=["--ignore-working-copy", "describe", "-m", "renamed"])
    pair.assert_parity()


def test_at_operation_reads_a_past_view(pair: RepoPair) -> None:
    """Op ids differ between the repos, so each side names its own."""
    chain(pair)
    pair.op(
        jj=["--at-operation", pair.op_id("cli", 2), "log"],
        py=["--at-operation", pair.op_id("py", 2), "log"],
    )
    pair.assert_parity()


def test_at_op_equals_form(pair: RepoPair) -> None:
    """`--at-op=<id>` is the short spelling of the same option."""
    chain(pair)
    pair.op(
        jj=[f"--at-op={pair.op_id('cli', 2)}", "status"],
        py=[f"--at-op={pair.op_id('py', 2)}", "status"],
    )
    pair.assert_parity()


# -- util ---------------------------------------------------------------


@pytest.mark.covers("util gc")
def test_util_gc_leaves_the_repo_alone(pair: RepoPair) -> None:
    """The default keeps everything written in the last two weeks, so a
    fresh repo loses nothing."""
    chain(pair)
    pair.op(jj=["util", "gc"])
    pair.assert_parity()


@pytest.mark.covers("util gc", "--expire")
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


@pytest.mark.covers("util snapshot")
def test_util_snapshot_with_a_dirty_working_copy(pair: RepoPair) -> None:
    """A changed file makes the snapshot real on both sides."""
    chain(pair)
    pair.op(files={"late.txt": b"late\n"}, jj=["util", "snapshot"])
    pair.assert_parity()


@pytest.mark.covers("util snapshot")
def test_util_snapshot_with_a_clean_working_copy(pair: RepoPair) -> None:
    """Nothing moved, so nothing is written and no operation is made."""
    chain(pair)
    pair.op(jj=["util", "snapshot"])
    pair.assert_parity()


@pytest.mark.covers("util gc", "--expire")
def test_util_gc_rejects_other_expire_values(pair: RepoPair) -> None:
    """jj accepts only the literal `now`."""
    chain(pair)
    pair.op(jj=["util", "gc", "--expire", "1h"], may_fail=True)
    pair.assert_parity()


# -- the root commit is immutable ---------------------------------------
#
# `root()` is the one commit that is immutable in every repository,
# including a local one with no remote where `trunk()` collapses to
# `root()`. jj refuses to rewrite it. jj_lib does not: it asserts, and an
# assertion inside a native extension aborts the process instead of
# raising, so pyjj has to refuse before the call. Each scenario asserts
# both sides fail and neither writes anything.

ROOT_REWRITE_ARGV = [
    ["describe", "-r", "root()", "-m", "nope"],
    ["abandon", "root()"],
    ["abandon", "--restore-descendants", "root()"],
    ["squash", "--into", "root()"],
    ["duplicate", "root()"],
    ["split", "-r", "root()", "base.txt"],
    ["rebase", "-r", "root()", "-d", "@"],
    ["metaedit", "-r", "root()", "--author", "Someone <someone@example.com>"],
    ["edit", "root()"],
    ["restore", "--into", "root()"],
    ["run", "-r", "root()", "true"],
    ["simplify-parents", "-r", "root()"],
    ["fix", "-s", "root()"],
    ["unsign", "-r", "root()"],
]
#
# `parallelize root()` is missing on purpose: the pinned jj panics on it.
# `parallelize` is the one rewrite command whose check covers only the
# commits whose parents change, and the root has none, so the argv
# reaches a `jj_lib` assertion. There is nothing to compare against.


@pytest.mark.covers("split", "-r")
@pytest.mark.covers("simplify-parents", "-r")
@pytest.mark.covers("fix", "-s")
@pytest.mark.covers("unsign", "-r")
@pytest.mark.covers("abandon", "--restore-descendants")
@pytest.mark.parametrize("argv", ROOT_REWRITE_ARGV, ids=lambda a: "_".join(a)[:40])
def test_rewriting_the_root_commit_must_fail(pair: RepoPair, argv) -> None:
    chain(pair)
    # State parity alone would pass a command that changed nothing and
    # still exited 0, which is exactly the bug this guards. `op()` returns
    # the pyjj-cli side's exit code; jj's side stays covered by the state
    # comparison.
    assert pair.op(jj=argv, may_fail=True) != 0
    pair.assert_parity()


# -- immutable commits ---------------------------------------------------
#
# `immutable()` is `present(trunk()) | tags() | untracked_remote_bookmarks()`.
# In a local repo with no remote, `trunk()` collapses to the root, so a
# tag is the only way to make a real commit immutable. Every scenario
# below tags `one`, which puts `base` and `one` out of reach and leaves
# `two` writable.


TAGGED_REWRITE_ARGV = [
    ["describe", "-r", rev("one"), "-m", "nope"],
    ["abandon", rev("one")],
    ["squash", "--into", rev("one")],
    ["squash", "--from", rev("one")],
    ["rebase", "-r", rev("one"), "-d", "root()"],
    ["rebase", "-s", rev("one"), "-d", "root()"],
    ["edit", rev("one")],
    ["restore", "--into", rev("one")],
    ["metaedit", "-r", rev("one"), "--author", "Someone <someone@example.com>"],
    ["run", "-r", rev("one"), "true"],
]


@pytest.mark.covers("describe", "-m", "-r")
@pytest.mark.covers("abandon")
@pytest.mark.covers("squash", "--into", "--from")
@pytest.mark.covers("rebase", "-r", "-s")
@pytest.mark.covers("edit")
@pytest.mark.covers("restore", "--into")
@pytest.mark.covers("metaedit", "--author", "-r")
@pytest.mark.covers("run", "-r")
@pytest.mark.parametrize("argv", TAGGED_REWRITE_ARGV, ids=lambda a: "_".join(a)[:40])
def test_rewriting_a_tagged_commit_must_fail(pair: RepoPair, argv) -> None:
    """A tag makes a commit immutable, so every rewrite that targets it
    must refuse and leave the repository alone."""
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    assert pair.op(jj=argv, may_fail=True) != 0
    pair.assert_parity()


@pytest.mark.covers("absorb", "--into")
def test_absorbing_into_a_tagged_commit_must_fail(pair: RepoPair) -> None:
    """`absorb` checks the destinations a hunk actually lands in, so the
    scenario has to produce one: the working copy edits `one.txt`, whose
    lines the tagged commit wrote. `--into` is needed too, because the
    default destination set is `mutable()`, which already excludes the
    tag."""
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.op(files={"one.txt": b"one edited\n"}, jj=["status"])
    assert pair.op(jj=["absorb", "--into", rev("one")], may_fail=True) != 0
    pair.assert_parity()


INSERT_AROUND_TAG_ARGV = [
    ["new", "-A", rev("one")],
    ["new", "-B", rev("two")],
    ["duplicate", rev("base"), "-A", rev("one")],
    ["revert", "-r", rev("base"), "-A", rev("one")],
    ["rebase", "-r", rev("three"), "-A", rev("one")],
    ["squash", "-A", rev("one")],
]


@pytest.mark.covers("new", "-m", "-A", "-B")
@pytest.mark.covers("duplicate", "-A")
@pytest.mark.covers("revert", "-r", "-A")
@pytest.mark.covers("rebase", "-r", "-A")
@pytest.mark.parametrize("argv", INSERT_AROUND_TAG_ARGV,
                         ids=lambda a: "_".join(a)[:40])
def test_inserting_before_a_tagged_commit_must_fail(pair: RepoPair, argv) -> None:
    """`-A` and `-B` rebase whatever followed the insertion point, so an
    immutable follower blocks the insertion even though the commit being
    inserted is brand new."""
    chain(pair)
    pair.op(jj=["new", "-m", "three"])
    pair.op(files={"three.txt": b"three\n"}, jj=["status"])
    pair.op(jj=["tag", "set", "v1", "-r", rev("two")])
    assert pair.op(jj=argv, may_fail=True) != 0
    pair.assert_parity()


def test_rewriting_below_a_tag_still_works(pair: RepoPair) -> None:
    """The check must not spread past what `immutable()` covers: `two` is
    a descendant of the tagged commit and stays writable."""
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", rev("one")])
    pair.op(jj=["describe", "-r", rev("two"), "-m", "two rewritten"])
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


@pytest.mark.covers("squash", "--keep-emptied", "-u")
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


@pytest.mark.covers("unsign", "-r")
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


@pytest.mark.covers("new", "-m")
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


@pytest.mark.covers("config set", "--repo")
@pytest.mark.covers("new", "-m")
def test_config_set_repo_changes_later_commits(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "set", "--repo", "user.name", "Bob"])
    pair.op(jj=["new", "-m", "after"])
    pair.assert_parity()


@pytest.mark.covers("config set", "--repo")
@pytest.mark.covers("config unset", "--repo")
@pytest.mark.covers("new", "-m")
def test_config_set_then_unset_restores_the_author(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "set", "--repo", "user.email", "bob@example.com"])
    pair.op(jj=["config", "unset", "--repo", "user.email"])
    pair.op(jj=["new", "-m", "after"])
    pair.assert_parity()


@pytest.mark.covers("config unset", "--repo")
def test_config_unset_a_missing_key_fails_on_both(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["config", "unset", "--repo", "user.name"], may_fail=True)
    pair.assert_parity()


@pytest.mark.covers("config set", "--repo")
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


@pytest.mark.covers("split", "--parallel", "-m")
def test_split_parallel_makes_siblings(pair: RepoPair) -> None:
    """`--parallel` puts the two halves side by side, so the second one
    hangs from the original's parents and loses the first one's changes."""
    chain(pair)
    pair.op(jj=["split", "--parallel", "two.txt", "-m", "half"])
    pair.assert_parity()


SPLIT_PLACEMENT_ARGV = [
    ["-A", "root()"],
    ["-B", rev("two")],
    ["--onto", "root()"],
    ["-d", rev("base")],
    ["-A", rev("base"), "-B", rev("two")],
]


@pytest.mark.covers("split", "-A", "-B", "--onto", "--destination", "-r")
@pytest.mark.parametrize("placement", SPLIT_PLACEMENT_ARGV,
                         ids=lambda a: "_".join(a)[:40])
def test_split_places_the_selected_half(pair: RepoPair, placement) -> None:
    """`--onto`/`-A`/`-B` send the selected changes elsewhere and leave
    the rest where the revision was. The half that stays keeps the
    original change id, which is the opposite of a plain split."""
    chain(pair)
    pair.op(jj=["split", "-r", rev("one"), *placement, "-m", "sel", "one.txt"])
    pair.assert_parity()


SPLIT_PLACEMENT_CONFLICTS = [
    ["--parallel", "-A", "root()"],
    ["--onto", "root()", "-A", "root()"],
    ["--onto", "root()", "-B", rev("two")],
]


@pytest.mark.covers("split", "--parallel", "-p")
@pytest.mark.parametrize("placement", SPLIT_PLACEMENT_CONFLICTS,
                         ids=lambda a: "_".join(a)[:40])
def test_split_rejects_conflicting_placement(pair: RepoPair, placement) -> None:
    """`--parallel` makes siblings and a placement flag moves one half
    away; `--onto` names the parents outright and `-A`/`-B` derive them.
    Neither pair can hold at once."""
    chain(pair)
    assert pair.op(jj=["split", "-r", rev("one"), *placement, "-m", "sel",
                       "one.txt"], may_fail=True) != 0
    pair.assert_parity()


def test_split_before_the_root_commit_must_fail(pair: RepoPair) -> None:
    """`-B root()` would rebase the root, so the follower check refuses
    it before anything is written."""
    chain(pair)
    assert pair.op(jj=["split", "-r", rev("one"), "-B", "root()", "-m", "sel",
                       "one.txt"], may_fail=True) != 0
    pair.assert_parity()


# -- inserting between two named revisions ------------------------------
#
# `-A` and `-B` given together name both sides of the insertion point, so
# the child keeps whatever other parents it had and gains the inserted
# commit. That is different from either flag alone, where the child's old
# parent IS the insertion point and gets replaced.


INSERT_BETWEEN_ARGV = [
    ["new", "-A", rev("base"), "-B", rev("two"), "-m", "ins"],
    ["new", "-A", rev("base"), "-m", "ins"],
    ["new", "-B", rev("two"), "-m", "ins"],
    ["revert", "-r", rev("one"), "-A", rev("base"), "-B", rev("two")],
    ["revert", "-r", rev("one"), "-A", rev("base")],
    ["revert", "-r", rev("one"), "-B", rev("two")],
    ["rebase", "-r", rev("one"), "-A", rev("base"), "-B", rev("two")],
    ["duplicate", rev("one"), "-A", rev("base"), "-B", rev("two")],
    ["split", "-r", rev("one"), "-A", rev("base"), "-B", rev("two"),
     "-m", "sel", "one.txt"],
]


@pytest.mark.covers("new", "-A", "-B")
@pytest.mark.covers("revert", "-A", "-B")
@pytest.mark.covers("rebase", "-A", "-B")
@pytest.mark.covers("duplicate", "-A", "-B")
@pytest.mark.parametrize("argv", INSERT_BETWEEN_ARGV,
                         ids=lambda a: "_".join(a)[:40])
def test_inserting_between_two_revisions(pair: RepoPair, argv) -> None:
    """`two` hangs from `one`, so naming `base` and `two` as the two sides
    makes `two` a merge: it keeps `one` and gains the inserted commit."""
    chain(pair)
    pair.op(jj=argv)
    pair.assert_parity()


@pytest.mark.covers("new", "-m")
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


@pytest.mark.covers("new", "-m")
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


@pytest.mark.covers("describe", "-m")
def test_op_revert_a_describe(pair: RepoPair) -> None:
    chain(pair)
    pair.op(jj=["describe", "-m", "renamed"])
    pair.op(jj=["op", "revert"])
    pair.assert_parity()


# -- what commands print -------------------------------------------------
#
# `assert_parity()` compares repository state, so a command that writes
# nothing is compared against nothing. `log`, `diff`, `show` and the
# rest had no coverage at all beyond their exit code. `assert_output()`
# runs a read-only argv on both sides and compares stdout verbatim,
# which is a fair bar: the two repos are bit-identical down to commit
# ids by then, so every id and column should line up.
#
# This is the gap the CLI-surface ledger cannot see. That ledger reads
# argument parsers, so a flag counts as covered once argparse accepts
# it. `diff --git` was the case in point: parsed for a long time, and
# ignored for just as long, until comparing its output caught it.
# Adding the remaining flags without this half would add more of the
# same.
#
# Which bar applies is a per-command decision, and there are three:
#
# - **Bytes.** A machine format has to match jj exactly, because a tool
#   downstream may refuse anything else: `diff --git`, `--stat`,
#   `--summary`, `--name-only`, `file list`, `file show`.
# - **Bytes, because matching came free.** `status`, `show` and the
#   default `diff` reached parity by binding jj's own presentation code
#   rather than by imitating its output, so the bytes agree and the
#   tests may as well say so.
# - **Facts.** `log` prints the author's name where jj prints the
#   email, and a timestamp without the century, both on request. Its
#   scenario asserts that nothing jj shows goes missing, not that the
#   columns line up. Adding a flag here means adding a fact to check,
#   not a column to match.
#
# `outputs()` covers the fourth case: a command whose output *should*
# differ per side, like `root`, which prints a path.
#
# What is still marked below fails today, strictly, so the count stays
# visible rather than absent.

OUTPUT_UNIMPLEMENTED = pytest.mark.xfail(
    strict=True,
    reason="pyjj-cli does not reproduce jj's output format for this command",
)


@pytest.mark.covers("log", "--reversed")
def test_log_reversed_puts_the_root_first(pair: RepoPair) -> None:
    """`--reversed` shows the oldest commit first. The rows diverge from
    jj's on purpose, as `log`'s do, so this checks the order."""
    chain(pair)
    _, forward = pair.outputs(["log"])
    _, backward = pair.outputs(["log", "--reversed"])
    rows = lambda text: [l for l in text.splitlines() if l[:1] in "@\u25cb\u25c6\u25cf"]
    assert rows(backward) == list(reversed(rows(forward)))
    assert "root()" in rows(backward)[0]


@pytest.mark.covers("log")
def test_log_draws_the_same_graph(pair: RepoPair) -> None:
    """`log`'s rows diverge from jj's on purpose. Its graph does not.

    The choice recorded in `log`'s `facts` bar is about what each row
    says -- the author's name, a timestamp without the century. The
    column of lanes to the left of it is jj's drawing, and a reader
    following a merge back to its parents needs it to be the same
    drawing. So this compares that column alone, on a history with a
    merge in it, where lanes actually branch and rejoin.

    Both sides draw with the same renderer -- jj's own `renderdag` --
    so a merge's fork lands on the line below its node, where jj puts
    it, rather than on the node's own line.
    """
    conflict_pair(pair)
    cli, py = pair.outputs(["log"])
    lanes = lambda text: [
        re.match(r"[@\u25cb\u25c6\u25cf~\u2502\u2500\u256d\u256e\u256f\u2570 ]*",
                 line).group(0).rstrip() or None
        for line in text.splitlines()
    ]
    cli_lanes, py_lanes = lanes(cli), lanes(py)
    assert any(lane and len(lane) > 1 for lane in cli_lanes), (
        f"scenario drew no branching graph\njj:\n{cli}"
    )
    assert cli_lanes == py_lanes, f"graph columns differ\njj:\n{cli}\npyjj:\n{py}"


@pytest.mark.covers("log")
def test_log_carries_the_facts_jj_shows(pair: RepoPair) -> None:
    """`log` is the one command where byte parity is not the goal.

    pyjj-cli prints the author's name where jj prints the email, and a
    timestamp without the century, because that was asked for. Equal or
    better is the bar, so this asserts that nothing jj shows goes
    missing: the same rows, the same ids, the same descriptions, the
    same bookmark, and `root()` on the root commit.

    The change ids have to match exactly, though, and not as a matter of
    taste. jj resolves only its reverse-hex spelling as a revset, so an
    id printed any other way is one the reader cannot paste back.
    """
    chain(pair)
    cli, py = pair.outputs(["log"])
    cli_rows = [line for line in cli.splitlines() if line[:1] in "@\u25cb\u25c6\u25cf"]
    py_rows = [line for line in py.splitlines() if line[:1] in "@\u25cb\u25c6\u25cf"]
    assert len(cli_rows) == len(py_rows), f"row counts differ\njj:\n{cli}\npyjj:\n{py}"

    ids = set(re.findall(r"\b[0-9a-f]{8}\b", cli)) | set(re.findall(r"\b[k-z]{8}\b", cli))
    missing = sorted(i for i in ids if i not in py)
    assert not missing, f"pyjj's log drops {missing}\njj:\n{cli}\npyjj:\n{py}"

    for fact in ("base", "one", "two", "main", "root()"):
        assert fact in py, f"pyjj's log drops {fact!r}\npyjj:\n{py}"


@pytest.mark.covers("diff")
def test_diff_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["diff", "-r", rev("one")])


@pytest.mark.covers("diff")
def test_diff_color_words_trims_context(pair: RepoPair) -> None:
    """The default format keeps three unchanged lines around a change
    and replaces the rest with `    ...`. This file is long enough for
    the rule to bite at the start, in the middle and at the end.
    """
    lines = [f"line{n}\n".encode() for n in range(1, 41)]
    pair.init()
    pair.op(files={"long.txt": b"".join(lines)}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "change"])
    changed = list(lines)
    changed[14] = b"LINE15\n"
    changed[34] = b"LINE35\n"
    pair.op(files={"long.txt": b"".join(changed)}, jj=["status"])
    pair.assert_output(["diff", "-r", "@"])


@pytest.mark.covers("diff")
def test_diff_color_words_prints_every_file_shape(pair: RepoPair) -> None:
    """Each shape gets its own sentence: a mode change reads as one, and
    an added empty file reads as `(empty)` rather than no lines."""
    pair.init()
    pair.op(
        files={
            "edited.txt": b"one\ntwo\n",
            "removed.txt": b"gone\n",
            "mode.txt": b"same content\n",
        },
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["new", "-m", "every shape"])
    pair.op(
        files={
            "edited.txt": b"one\nTWO\n",
            "removed.txt": None,
            "added.txt": b"brand new\n",
            "empty.txt": b"",
        },
        jj=["file", "chmod", "x", "mode.txt"],
    )
    pair.assert_output(["diff", "-r", "@"])


@pytest.mark.covers("diff", "--git")
def test_diff_git_format_output_matches(pair: RepoPair) -> None:
    """`--git` is parsed by both, so the surface ledger counted it as
    present while it printed nothing. Only comparing what it prints says
    whether it works.

    Byte parity is the right bar here, unlike the human-readable
    formats: a git-format diff is a machine format, and a patch that
    differs from jj's is a patch some other tool may refuse.
    """
    chain(pair)
    pair.assert_output(["diff", "--git", "-r", rev("one")])


@pytest.mark.covers("diff", "--git")
def test_diff_git_format_prints_every_file_shape(pair: RepoPair) -> None:
    """The chain fixture holds plain additions only. A git-format diff
    has five other shapes, and each prints its own header lines:
    a modification, a deletion, a new file, a mode-only change, and a
    file with no trailing newline.

    The last one is the reason the hunks come from a binding rather than
    from Python's `difflib`: jj prints `\\ No newline at end of file`
    under both sides, and its hunk boundaries are its own.
    """
    pair.init()
    pair.op(
        files={
            "edited.txt": b"one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\n",
            "removed.txt": b"gone\n",
            "mode.txt": b"same content\n",
            "nonewline.txt": b"no trailing newline",
        },
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["new", "-m", "every shape"])
    pair.op(
        files={
            "edited.txt": b"one\nTWO\nthree\nfour\nfive\nsix\nseven\nEIGHT\n",
            "removed.txt": None,
            "added.txt": b"brand new\n",
            "nonewline.txt": b"no trailing newline, now longer",
        },
        jj=["file", "chmod", "x", "mode.txt"],
    )
    pair.assert_output(["diff", "--git", "-r", "@"])


@pytest.mark.covers("diff", "--git")
def test_diff_git_format_reads_a_root_commit(pair: RepoPair) -> None:
    """A commit with no parent diffs against the root commit, whose tree
    is empty, so every file reads as a new file."""
    pair.init()
    pair.op(files={"first.txt": b"first\n"}, jj=["describe", "-m", "root child"])
    pair.assert_output(["diff", "--git", "-r", "@"])


@pytest.mark.covers("bookmark list")
def test_bookmark_list_output_matches(pair: RepoPair) -> None:
    """A bookmark lists as `name: <commit summary>`, and the summary
    carries no bookmark name of its own -- the line already names it."""
    chain(pair)
    pair.assert_output(["bookmark", "list"])


@pytest.mark.covers("bookmark list")
@pytest.mark.covers("bookmark delete")
def test_bookmark_list_drops_a_deleted_bookmark(pair: RepoPair) -> None:
    """A deleted local-only bookmark leaves nothing behind, so both
    sides print nothing.

    jj's `name (deleted)` line is for a bookmark that still has a
    remote-tracking counterpart. `_print_bookmark` writes it, and no
    scenario reaches it yet -- this repository has no remote.
    """
    chain(pair)
    pair.op(jj=["bookmark", "delete", "main"])
    pair.assert_output(["bookmark", "list"])


@pytest.mark.covers("workspace list")
def test_workspace_list_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["workspace", "list"])


@pytest.mark.covers("diff", "--stat")
def test_diff_stat_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["diff", "--stat", "-r", rev("one")])


@pytest.mark.covers("file list")
def test_file_list_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["file", "list"])


@pytest.mark.covers("evolog")
def test_evolog_carries_the_facts_jj_shows(pair: RepoPair) -> None:
    """`evolog` cannot be compared byte for byte, for two reasons.

    Its rows share `log`'s deliberate divergence, and every row names
    the operation that made that version -- and operation ids are
    repo-local, so the two sides differ there however correct both are.
    Hence facts: one row per version, every commit id jj shows, the
    change id, and `(hidden)` on the versions jj calls hidden.
    """
    chain(pair)
    pair.op(files={"two.txt": b"two again\n"}, jj=["describe", "-m", "two rewritten"])
    cli, py = pair.outputs(["evolog"])
    cli_rows = [line for line in cli.splitlines() if line[:1] in "@\u25cb\u25c6\u25cf"]
    py_rows = [line for line in py.splitlines() if line[:1] in "@\u25cb\u25c6\u25cf"]
    # Guard the scenario itself: without a rewrite there is nothing
    # hidden to find, and every assertion below would pass on empty.
    assert len(cli_rows) > 1, f"scenario produced no evolution\njj:\n{cli}"
    assert cli.count("(hidden)") >= 1, f"scenario hid nothing\njj:\n{cli}"
    assert len(cli_rows) == len(py_rows), f"row counts differ\njj:\n{cli}\npyjj:\n{py}"
    assert cli.count("(hidden)") == py.count("(hidden)"), (
        f"hidden markers differ\njj:\n{cli}\npyjj:\n{py}"
    )
    ids = set(re.findall(r"\b[0-9a-f]{8}\b", cli)) | set(re.findall(r"\b[k-z]{8}\b", cli))
    # Operation ids are repo-local, so drop the ones only they contribute.
    op_ids = set(re.findall(r"operation ([0-9a-f]{12})", cli))
    ids = {i for i in ids if not any(i in op for op in op_ids)}
    missing = sorted(i for i in ids if i not in py)
    assert not missing, f"pyjj's evolog drops {missing}\njj:\n{cli}\npyjj:\n{py}"


@pytest.mark.covers("bookmark list", "--template", "-T")
def test_bookmark_list_renders_a_jinja_template(pair: RepoPair) -> None:
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["bookmark", "list", "-T", 'name ++ " " ++ normal_target.commit_id().short(8) ++ "\n"'],
        ["bookmark", "list", "-T", "{{ name }} {{ commit_id_short }}"],
    )
    assert cli == py


@pytest.mark.covers("tag list", "--template", "-T")
def test_tag_list_renders_a_jinja_template(pair: RepoPair) -> None:
    """No tags here, so both sides print nothing -- which still pins
    that a template does not make a listing invent rows."""
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["tag", "list", "-T", 'name ++ "\n"'],
        ["tag", "list", "-T", "{{ name }}"],
    )
    assert cli == py


@pytest.mark.covers("workspace list", "--template", "-T")
def test_workspace_list_renders_a_jinja_template(pair: RepoPair) -> None:
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["workspace", "list", "-T", 'name ++ " " ++ target.commit_id().short(8) ++ "\n"'],
        ["workspace", "list", "-T", "{{ name }} {{ commit_id_short }}"],
    )
    assert cli == py


@pytest.mark.covers("show", "--template", "-T")
def test_show_renders_a_jinja_template(pair: RepoPair) -> None:
    """`show`'s template replaces the header block. The diff below it
    still prints, as it does for jj."""
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["show", "-T", 'commit_id.short(8) ++ "\n"', rev("one")],
        ["show", "-T", "{{ commit_id_short }}", rev("one")],
    )
    assert cli == py


@pytest.mark.covers("operation log", "--template", "-T")
def test_op_log_renders_a_jinja_template(pair: RepoPair) -> None:
    """A template of one's own, rather than a builtin name.

    The corpus covers the builtin names, whose argv is shared. This
    covers the other path: a raw template, spelled in each side's own
    language. It asks for descriptions only, because an operation id is
    minted per repository and could never agree.
    """
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["op", "log", "--no-graph", "-T",
         'self.description().first_line() ++ "\n"'],
        ["op", "log", "--no-graph", "-T", "{{ description }}"],
    )
    assert cli == py
    assert "snapshot working copy" in cli, f"scenario printed nothing\n{cli}"


@pytest.mark.covers("evolog", "--template", "-T")
def test_evolog_renders_a_jinja_template(pair: RepoPair) -> None:
    """`evolog` takes a template, as jj does, and pyjj-cli's template
    language is Jinja rather than jj's own.

    So the argv cannot be shared: the two sides get the same request
    written in each one's language, and the output has to agree.
    """
    chain(pair)
    cli, py = pair.outputs_asymmetric(
        ["evolog", "--no-graph", "-T", 'commit.commit_id().short(8) ++ "\n"'],
        ["evolog", "--no-graph", "-T", "{{ commit_id_short }}"],
    )
    assert cli == py


@pytest.mark.covers("interdiff")
def test_interdiff_output_matches(pair: RepoPair) -> None:
    """`interdiff` compares two commits' patches, and their
    descriptions, so its output leads with a description block."""
    chain(pair)
    pair.assert_output(["interdiff", "--from", rev("one"), "--to", rev("two")])


@pytest.mark.covers("interdiff", "--git")
def test_interdiff_git_format_output_matches(pair: RepoPair) -> None:
    """In `--git` format the description diff gets a dummy path, so the
    whole output stays a parsable patch."""
    chain(pair)
    pair.assert_output(
        ["interdiff", "--git", "--from", rev("one"), "--to", rev("two")]
    )


@pytest.mark.covers("interdiff", "--summary")
def test_interdiff_summary_omits_the_description(pair: RepoPair) -> None:
    """The short formats leave the description out: a summary line is
    only a path, and the description has none."""
    chain(pair)
    pair.assert_output(
        ["interdiff", "--summary", "--from", rev("one"), "--to", rev("two")]
    )


@pytest.mark.covers("file annotate")
def test_file_annotate_output_matches(pair: RepoPair) -> None:
    """Each line names the change that last touched it, not the commit:
    a change id is what jj resolves back to a revision."""
    chain(pair)
    pair.assert_output(["file", "annotate", "one.txt"])


@pytest.mark.covers("file show")
def test_file_show_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["file", "show", "one.txt"])


@pytest.mark.covers("tag list")
def test_tag_list_output_matches(pair: RepoPair) -> None:
    """Nothing here has a tag, so both sides print nothing -- which is
    still worth pinning: printing something would be the bug."""
    chain(pair)
    pair.assert_output(["tag", "list"])


@pytest.mark.covers("util backend name")
def test_util_backend_name_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["util", "backend", "name"])


@pytest.mark.covers("root")
def test_root_prints_the_workspace_root(pair: RepoPair) -> None:
    """`jj root` prints a path, and the two workspaces are at different
    paths by construction, so each side is checked against its own."""
    chain(pair)
    cli, py = pair.outputs(["root"])
    assert cli.strip() == str(pair.cli_repo)
    assert py.strip() == str(pair.py_repo)


@pytest.mark.covers("workspace root")
def test_workspace_root_prints_the_workspace_root(pair: RepoPair) -> None:
    chain(pair)
    cli, py = pair.outputs(["workspace", "root"])
    assert cli.strip() == str(pair.cli_repo)
    assert py.strip() == str(pair.py_repo)


@pytest.mark.covers("diff", "--summary", "-s")
def test_diff_summary_output_matches(pair: RepoPair) -> None:
    """`--summary` prints one status letter and the path. pyjj-cli used
    to print the status word instead, padded to a column."""
    chain(pair)
    pair.assert_output(["diff", "--summary", "-r", rev("one")])
    pair.assert_output(["diff", "-s", "-r", rev("one")])


@pytest.mark.covers("diff", "--name-only")
def test_diff_name_only_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["diff", "--name-only", "-r", rev("one")])


@pytest.mark.covers("diff", "--summary")
def test_diff_summary_reads_a_root_commit(pair: RepoPair) -> None:
    """A parentless commit diffs against the root commit, so every file
    in it reads as added."""
    pair.init()
    pair.op(files={"first.txt": b"first\n"}, jj=["describe", "-m", "root child"])
    pair.assert_output(["diff", "--summary", "-r", "@"])


@pytest.mark.covers("status")
def test_status_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["status"])


@pytest.mark.covers("status")
def test_status_reports_a_clean_working_copy(pair: RepoPair) -> None:
    """A working copy with nothing in it prints one sentence instead of
    a change list, and its parent is the root commit."""
    pair.init()
    pair.assert_output(["status"])


@pytest.mark.covers("status")
def test_status_reports_conflicts(pair: RepoPair) -> None:
    """A conflicted working copy makes jj print more than the change
    list: a `(conflict)` marker in the commit summary, a warning, and
    the conflicted paths under it."""
    conflict_pair(pair)
    pair.assert_output(["status"])


@pytest.mark.covers("status")
def test_status_names_a_bookmark_on_the_parent(pair: RepoPair) -> None:
    """The commit summary puts bookmarks before the description, with
    ` | ` between them."""
    chain(pair)
    pair.op(jj=["new", rev("one")])
    pair.assert_output(["status"])


@pytest.mark.covers("show")
def test_show_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["show", rev("one")])


@pytest.mark.covers("show")
def test_show_prints_bookmarks_and_a_long_description(pair: RepoPair) -> None:
    """The header carries a `Bookmarks:` line only when there are some,
    and it names an exported bookmark twice -- `main` and `main@git`.

    The description is indented by four, except that a blank line stays
    blank rather than becoming four spaces.
    """
    pair.init()
    pair.op(files={"f.txt": b"one\n"}, jj=["describe", "-m", "subject\n\nbody line\n"])
    pair.op(jj=["bookmark", "create", "main"])
    pair.assert_output(["show", "@"])


@pytest.mark.covers("show", "--no-patch")
def test_show_no_patch_output_matches(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_output(["show", "--no-patch", rev("one")])


# -- the other spellings of split, new and commit ------------------------------
#
# jj gives most of its options a long name and a short one, and several
# a second long name on top. Every spelling is its own item on the
# checklist, because a parser can accept one and miss another.

SPLIT_SPELLING_ARGV = [
    ["--insert-after", rev("base")],
    ["--after", rev("base")],
    ["--insert-before", rev("two")],
    ["--before", rev("two")],
    ["-o", "root()"],
]


@pytest.mark.covers("split", "--insert-after", "--after")
@pytest.mark.covers("split", "--insert-before", "--before")
@pytest.mark.covers("split", "-o", "--revision", "--message")
@pytest.mark.parametrize("placement", SPLIT_SPELLING_ARGV,
                         ids=lambda a: a[0].lstrip("-"))
def test_split_by_each_spelling(pair: RepoPair, placement) -> None:
    chain(pair)
    pair.op(jj=["split", "--revision", rev("one"), *placement,
                "--message", "sel", "one.txt"])
    pair.assert_parity()


@pytest.mark.covers("split", "--editor")
def test_split_editor_opens_over_an_explicit_message(pair: RepoPair) -> None:
    """`-m` normally means no editor. `--editor` opens one anyway, and
    what it writes is what the first half keeps.

    The revision being split has no description, so jj asks about the
    first half only. A described one would open the editor twice, once
    a half.
    """
    pair.init()
    pair.op(files={"one.txt": b"one\n", "two.txt": b"two\n"}, jj=["status"])
    pair.op(jj=["split", "one.txt", "-m", "typed", "--editor"],
            editor_spec={"op": "set", "value": "written by the editor\n"})
    pair.assert_parity()


NEW_SPELLING_ARGV = [
    ["-o", rev("base")],
    ["-r", rev("base")],
    ["--insert-after", rev("base")],
    ["--after", rev("base")],
    ["--insert-before", rev("two")],
    ["--before", rev("two")],
]


@pytest.mark.covers("new", "-o", "-r", "--message")
@pytest.mark.covers("new", "--insert-after", "--after")
@pytest.mark.covers("new", "--insert-before", "--before")
@pytest.mark.parametrize("argv", NEW_SPELLING_ARGV,
                         ids=lambda a: a[0].lstrip("-"))
def test_new_by_each_spelling(pair: RepoPair, argv) -> None:
    """`-o` and `-r` are the parents `jj new` also takes positionally.
    jj hides both, and documents them on the positional itself."""
    chain(pair)
    pair.op(jj=["new", *argv, "--message", "fresh"])
    pair.assert_parity()


@pytest.mark.covers("commit", "--message", "--editor")
def test_commit_editor_opens_over_an_explicit_message(pair: RepoPair) -> None:
    """The same rule `split` and `squash` follow: `--editor` opens an
    editor that `-m` alone would have skipped."""
    pair.init()
    pair.op(files={"a.txt": b"a\n"},
            jj=["commit", "--message", "typed", "--editor"],
            editor_spec={"op": "set", "value": "written by the editor\n"})
    pair.assert_parity()


@pytest.mark.covers("commit", "--tool")
def test_commit_via_diff_tool_keeps_one_file(pair: RepoPair) -> None:
    """The diff editor picks what stays in the commit; the rest becomes
    the new working copy."""
    two_file_change(pair)
    pair.op(jj=["commit", "--tool", "parity-diff", "-m", "first"],
            diff_spec={"op": "keep", "paths": ["one.txt"]})
    pair.assert_parity()


@pytest.mark.covers("commit", "--tool")
def test_commit_diff_tool_selecting_nothing_is_allowed(pair: RepoPair) -> None:
    """`jj squash --tool` refuses a selection that moves nothing. This
    one does not: the commit ends up empty and the whole change goes to
    the new working copy, which is a state a reader can undo."""
    two_file_change(pair)
    pair.op(jj=["commit", "--tool", "parity-diff", "-m", "first"],
            diff_spec={"op": "drop", "paths": ["one.txt", "two.txt"]})
    pair.assert_parity()
