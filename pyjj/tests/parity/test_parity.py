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
