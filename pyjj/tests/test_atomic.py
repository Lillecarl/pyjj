"""Session verbs that had to be proven, not trusted.

`Atomic.restore` once returned its builder without writing it, so the
rewrite evaporated and the block died in conflict-check with no hint.
`Atomic.revert` did not exist at all, forcing multi-op CLI chains for
a one-transaction job. Restoring an unknown path succeeded silently.
Each test below pins one of those to the tree, not to a message.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def session(tmp_path, monkeypatch):
    """Two described commits (`first`, `second`), opened through the API."""
    root = tmp_path / "repo"
    root.mkdir()
    home = tmp_path / "config"
    home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("JJ_USER", "tester")
    monkeypatch.setenv("JJ_EMAIL", "tester@example.com")

    env = os.environ.copy()
    subprocess.run([sys.executable, "-m", "pyjj_cli", "git", "init"],
                   cwd=str(root), env=env, capture_output=True, check=True)
    for name, text in (("first", "one\n"), ("second", "two\n")):
        (root / f"{name}.txt").write_text(text)
        subprocess.run(
            [sys.executable, "-m", "pyjj_cli", "-R", str(root),
             "commit", "-m", name],
            env=env, capture_output=True, check=True)
    return pyjj.open(str(root))


def _by_description(repo, word):
    found = [c for c in repo.revset("all()")
             if c.description.strip() == word]
    assert len(found) == 1, f"{word!r} names {len(found)} commits"
    return found[0]


def test_restore_lands_in_the_tree(session):
    """The restored file reads back from the rewritten commit."""
    (Path(session.root) / "first.txt").write_text("edited\n")
    with session.atomic("undo that edit") as tx:
        written = tx.restore(["first.txt"])
    assert written.read_file("first.txt") == b"one\n"
    assert _by_description(session, "second").read_file("first.txt") \
        == b"one\n"


def test_restore_of_an_unknown_path_is_refused(session):
    (Path(session.root) / "first.txt").write_text("edited\n")
    with pytest.raises(pyjj.PyjjError, match="no such file"):
        with session.atomic("restore a typo") as tx:
            tx.restore(["no-such-file.txt"])


def test_revert_chains_two_commits_in_one_operation(session):
    second = _by_description(session, "second")
    first = _by_description(session, "first")
    before = len(session.reload()._repo.operation_log())
    with session.atomic("back out the stack") as tx:
        made = tx.revert([second.change_id.reverse_hex(),
                          first.change_id.reverse_hex()],
                         destination=second.change_id.reverse_hex())
    assert [c.description.splitlines()[0] for c in made] == [
        'Revert "second"', 'Revert "first"']
    assert made[0].parent_ids[0].hex() == second.id.hex()
    assert made[1].parent_ids[0].hex() == made[0].id.hex()
    after = len(session.reload()._repo.operation_log())
    assert after == before + 1
