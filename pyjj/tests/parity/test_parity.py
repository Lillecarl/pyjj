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

import pytest

from parity_harness import RepoPair

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
