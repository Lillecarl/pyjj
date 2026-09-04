"""Fixtures for the parity suite."""

from pathlib import Path

import pytest

from parity_harness import RepoPair


def build_chain(pair: RepoPair) -> None:
    """base <- one <- two, with base.txt/one.txt/two.txt and bookmark
    main on 'one' -- the shared prefix most scenarios start from.

    This is the definition; `test_parity.chain()` restores a copy of the
    result rather than replaying it.
    """
    pair.init()
    pair.op(files={"base.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"one.txt": b"one\n"}, jj=["bookmark", "create", "main"])
    pair.op(jj=["new", "-m", "two"])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"])


@pytest.fixture(scope="session")
def chain_template(tmp_path_factory):
    """Build the `chain` starting state once per session.

    Replaying it costs ten CLI runs, about 3.7 seconds, and 164 tests
    start from it. Copying the built result costs about 34 milliseconds.

    Under xdist this runs once per worker, which is the right trade: a
    few seconds of setup against minutes of replay.
    """
    root = tmp_path_factory.mktemp("chain-template")
    pair = RepoPair(root / "build")
    build_chain(pair)
    step = pair.save_template(root / "template")
    return root / "template", step


@pytest.fixture
def pair(tmp_path: Path, chain_template) -> RepoPair:
    p = RepoPair(tmp_path)
    p.chain_template = chain_template
    return p
