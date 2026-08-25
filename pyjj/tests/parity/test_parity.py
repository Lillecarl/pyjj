"""Conformance scenarios: the same operations through real jj and pyjj
must produce bit-identical repositories (see parity_harness module docs).

Each test builds a RepoPair in its own tmp_path, walks one scenario as a
sequence of `pair.op(...)` steps, then asserts parity. A failure's
unified diff is the bug report: it names exactly which commit, bookmark,
working-copy pointer or file diverged.

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
    pair.op(
        files={"base.txt": b"base\n"},
        jj=["describe", "-m", "base"],
        py_ops=[{"op": "snapshot"}, {"op": "describe", "message": "base"}],
    )
    pair.op(jj=["new", "-m", "one"], py_ops=[{"op": "new", "message": "one"}])
    pair.op(
        files={"one.txt": b"one\n"},
        jj=["bookmark", "create", "main"],
        py_ops=[{"op": "snapshot"}, {"op": "bookmark", "name": "main"}],
    )
    pair.op(jj=["new", "-m", "two"], py_ops=[{"op": "new", "message": "two"}])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"], py_ops=[{"op": "snapshot"}])


def test_init_only(pair: RepoPair) -> None:
    pair.init()
    pair.assert_parity()


def test_describe_and_commit_chain(pair: RepoPair) -> None:
    chain(pair)
    pair.assert_parity()


def test_squash_non_wc_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["squash", "-r", rev("one"), "-u"],
        py_ops=[{"op": "squash", "revision": rev("one")}],
    )
    pair.assert_parity()


def test_rebase_revision_onto_sibling(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["new", rev("base"), "-m", "side"],
        py_ops=[{"op": "new", "message": "side", "parents": [rev("base")]}],
    )
    # Rebasing 'one' onto 'side' must drag descendant 'two' along on both
    # sides, leaving the same rewritten graph.
    pair.op(
        jj=["rebase", "-r", rev("one"), "-d", rev("side")],
        py_ops=[
            {"op": "rebase", "revision": rev("one"), "destination": rev("side")}
        ],
    )
    pair.assert_parity()


def test_abandon_middle_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["abandon", rev("one")],
        py_ops=[{"op": "abandon", "revision": rev("one")}],
    )
    pair.assert_parity()


def test_duplicate_commit(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["duplicate", rev("one")],
        py_ops=[{"op": "duplicate", "revision": rev("one")}],
    )
    pair.assert_parity()


def test_bookmark_move(pair: RepoPair) -> None:
    chain(pair)
    pair.op(
        jj=["bookmark", "set", "main", "-r", rev("two")],
        py_ops=[{"op": "bookmark", "name": "main", "target": rev("two")}],
    )
    pair.assert_parity()
