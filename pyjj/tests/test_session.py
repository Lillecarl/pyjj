"""What `pyjj.open()` and `repo.atomic()` promise.

The promise under test is the one the wrapper exists for: a block is
all-or-nothing. Every failure case therefore compares the repository
before and after by commit id, rather than trusting a message.

In-process, because the API is a library; `pyjj python` gets one
subprocess test of its own, since carrying the interpreter is the
whole point of that subcommand.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyjj


def _state(repo) -> dict:
    """Every commit, as `{change id: (commit id, description)}`."""
    return {c.change_id.reverse_hex(): (c.id.hex(), c.description.strip())
            for c in repo.reload().revset("all()")}


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A repository with two described commits, opened through the API."""
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


def test_open_names_the_repository(session):
    assert Path(session.root).name == "repo"
    assert "repo" in repr(session)


def test_open_outside_a_repository_says_so(tmp_path):
    with pytest.raises(pyjj.PyjjError, match="no jj repository"):
        pyjj.open(str(tmp_path))


def test_a_clean_block_is_applied(session):
    with session.atomic("retitle") as tx:
        tx.describe("@-", message="renamed")
    assert any(description == "renamed"
               for _id, description in _state(session).values())


def test_a_failed_block_writes_nothing(session):
    """The whole promise, stated as bytes rather than as a message."""
    before = _state(session)
    with pytest.raises(RuntimeError):
        with session.atomic("should write nothing") as tx:
            tx.describe("@-", message="CHANGED")
            raise RuntimeError("boom")
    assert _state(session) == before


def test_a_failed_block_leaves_no_operation_either(session):
    """Discarding a transaction is not the same as undoing it: there is
    no operation to show, because none was ever created."""
    before = session.reload().operation_id
    with pytest.raises(RuntimeError):
        with session.atomic("nothing") as tx:
            tx.describe("@-", message="CHANGED")
            raise RuntimeError("boom")
    assert session.reload().operation_id == before


def test_a_pyjj_error_inside_a_block_is_explained(session):
    with pytest.raises(pyjj.PyjjError, match="Nothing was written"):
        with session.atomic("bad revision") as tx:
            tx.describe("nonexistent-revision", message="x")


def test_later_operations_see_the_earlier_ones(session):
    """The trap this wrapper exists to close.

    `ReadonlyRepo` answers from the state the transaction started in,
    so a second operation naming `@-` addressed a commit the first had
    already replaced -- and rewriting it left the change divergent.
    """
    with session.atomic("squash then retitle") as tx:
        tx.squash("@-", into="@--")
        tx.describe("@-", message="both, together")

    changes = [c.change_id.reverse_hex() for c in session.reload().revset("all()")]
    assert len(changes) == len(set(changes)), "the block left a divergent change"
    assert any(c.description.strip() == "both, together"
               for c in session.revset("all()"))


def test_rebase_wants_exactly_one_placement(session):
    with pytest.raises(pyjj.PyjjError, match="exactly one"):
        with session.atomic("bad rebase") as tx:
            tx.rebase("@", destination="@-", after="@--")
    with pytest.raises(pyjj.PyjjError, match="exactly one"):
        with session.atomic("bad rebase") as tx:
            tx.rebase("@")


def test_squash_with_nothing_to_move_says_so(session):
    before = _state(session)
    with pytest.raises(pyjj.PyjjError, match="nothing to move"):
        with session.atomic("empty squash") as tx:
            tx.squash("@-", into="@--", paths=["not-a-file.txt"])
    assert _state(session) == before


def test_new_and_describe_compose(session):
    with session.atomic("branch off") as tx:
        tx.new("@--", message="a third line")
    assert any(c.description.strip() == "a third line"
               for c in session.reload().revset("all()"))


def test_bookmark_is_set_inside_the_block(session):
    with session.atomic("name it") as tx:
        tx.bookmark("topic", "@-")
    names = [b.name for b in session.reload()._repo.bookmarks()]
    assert "topic" in names


def test_a_bookmark_is_not_set_when_the_block_fails(session):
    with pytest.raises(RuntimeError):
        with session.atomic("name it") as tx:
            tx.bookmark("topic", "@-")
            raise RuntimeError("boom")
    names = [b.name for b in session.reload()._repo.bookmarks()]
    assert "topic" not in names


def test_cli_python_binds_pyjj_and_repo(tmp_path):
    """`pyjj python` exists to carry the interpreter, so this one goes
    through the real command."""
    root = tmp_path / "repo"
    root.mkdir()
    home = tmp_path / "config"
    home.mkdir()
    env = os.environ.copy()
    env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
               XDG_CONFIG_HOME=str(home))
    subprocess.run([sys.executable, "-m", "pyjj_cli", "git", "init"],
                   cwd=str(root), env=env, capture_output=True, check=True)

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "python", "-"],
        input="print(pyjj.__name__, repo.root, pyjj_bindings.__name__)\n",
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "pyjj" in result.stdout
    assert str(root) in result.stdout


def test_cli_python_still_binds_pyjj_without_a_repo(tmp_path):
    """`--no-repo` drops the repository, never the modules."""
    env = os.environ.copy()
    env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
               XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "python", "--no-repo", "-c",
         "print(pyjj.__name__, repo)"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "pyjj None" in result.stdout


@pytest.fixture
def colliding(tmp_path, monkeypatch):
    """Two topics off `main` touching the same file, so stacking one on
    the other conflicts."""
    root = tmp_path / "collide"
    root.mkdir()
    home = tmp_path / "collide-config"
    home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("JJ_USER", "tester")
    monkeypatch.setenv("JJ_EMAIL", "tester@example.com")
    env = os.environ.copy()

    def run(*args, cwd=None):
        result = subprocess.run(
            [sys.executable, "-m", "pyjj_cli", *args],
            cwd=cwd or str(root), env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result

    run("git", "init")
    (root / "base.txt").write_text("base\n")
    run("-R", str(root), "commit", "-m", "base")
    run("-R", str(root), "bookmark", "create", "main", "-r", "@-")
    for topic in ("a", "b"):
        run("-R", str(root), "new", "main", "-m", f"topic {topic}")
        (root / "shared.txt").write_text(topic + "\n")
        run("-R", str(root), "bookmark", "create", topic, "-r", "@")
    run("-R", str(root), "new", "b", "-m", "keepalive")
    return pyjj.open(str(root)), root, home


def test_a_conflict_discards_the_block(colliding):
    """A graph of topology cannot have asked for a conflict, so the
    default refuses one the block introduced."""
    session, _root, _home = colliding
    before = _state(session)
    with pytest.raises(pyjj.PyjjError, match="in conflict"):
        with session.atomic("stack b on a") as tx:
            tx.rebase("b", destination="a")
    assert _state(session) == before


def test_allow_conflicts_keeps_the_result(colliding):
    session, _root, _home = colliding
    with session.atomic("stack b on a", allow_conflicts=True) as tx:
        tx.rebase("b", destination="a")
    assert session.reload().conflicts(), "nothing ended up conflicted"


def test_an_immutable_commit_is_refused(colliding):
    """jj's own guard, reachable because settings carry the repo layer."""
    session, root, _home = colliding
    env = os.environ.copy()
    subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "config", "set",
         "--repo", 'revset-aliases."immutable_heads()"', "a"],
        env=env, capture_output=True, check=True)

    session = pyjj.open(str(root))
    before = _state(session)
    with pytest.raises(pyjj.PyjjError, match="immutable"):
        with session.atomic("rewrite a") as tx:
            tx.describe("a", message="should be refused")
    assert _state(session) == before


def test_allow_immutable_lets_it_through(colliding):
    session, root, _home = colliding
    env = os.environ.copy()
    subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "config", "set",
         "--repo", 'revset-aliases."immutable_heads()"', "a"],
        env=env, capture_output=True, check=True)

    session = pyjj.open(str(root))
    with session.atomic("rewrite a", allow_immutable=True) as tx:
        tx.describe("a", message="allowed through")
    assert any(c.description.strip() == "allowed through"
               for c in session.reload().revset("all()"))


def test_restore_undoes_a_file_in_the_working_copy(session):
    """`jj restore <path>`: take the parent's version back."""
    root = Path(session.root)
    (root / "first.txt").write_text("edited\n")
    with session.atomic("undo that edit") as tx:
        tx.restore(["first.txt"])
    assert (root / "first.txt").read_text() == "one\n"


def test_absorb_moves_a_change_into_the_commit_that_owns_it(session):
    """`jj absorb`: the edit lands in the commit that last touched the
    line, without the caller naming which one that is."""
    root = Path(session.root)
    (root / "first.txt").write_text("one edited\n")

    with session.atomic("absorb") as tx:
        tx.absorb()

    session.reload()
    first = next(c for c in session.revset("all()")
                 if c.description.strip() == "first")
    assert first.read_file("first.txt") == b"one edited\n", (
        "the edit did not reach the commit that introduced the line")
