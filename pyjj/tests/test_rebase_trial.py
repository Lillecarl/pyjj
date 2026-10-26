"""`rebase --dry-run` and `rebase --abort-on-conflict`: pyjj's own flags.

Both work out the rebase in full inside the transaction and decide
afterwards whether to commit it. So each refusal compares the commit
ids before and after, rather than trusting the message.
"""

import os
import subprocess
import sys

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


def _env(home):
    environment = os.environ.copy()
    environment.update(JJ_ENV)
    environment["XDG_CONFIG_HOME"] = str(home)
    return environment


def _run(root, *args, home):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
        capture_output=True, text=True, env=_env(home),
    )


def _state(root, home) -> str:
    result = _run(root, "log", "-r", "all() ~ root()", "--no-graph",
                  "-T", "{{ change_id_short }}={{ commit_id_short_raw }};",
                  home=home)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def topics(tmp_path):
    """`main` with topics `a` and `b` off it, and `keepalive` on `b`.

    With `shared`, both topics add the same file with different content,
    so stacking `b` on `a` conflicts.
    """
    def build(shared: bool):
        root = tmp_path / "repo"
        root.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "pyjj_cli", "git", "init"],
            capture_output=True, text=True, env=_env(home), cwd=str(root),
        )
        assert result.returncode == 0, result.stderr
        (root / "base.txt").write_text("base\n")
        _run(root, "commit", "-m", "base", home=home)
        _run(root, "bookmark", "create", "main", "-r", "@-", home=home)
        for topic in ("a", "b"):
            _run(root, "new", "main", "-m", f"topic {topic}", home=home)
            name = "shared.txt" if shared else f"{topic}.txt"
            (root / name).write_text(topic + "\n")
            _run(root, "bookmark", "create", topic, "-r", "@", home=home)
        _run(root, "new", "b", "-m", "keepalive", home=home)
        return root, home
    return build


def test_abort_on_conflict_commits_a_clean_rebase(topics):
    root, home = topics(shared=False)
    before = _state(root, home)
    result = _run(root, "rebase", "-s", "b", "-d", "a",
                  "--abort-on-conflict", home=home)
    assert result.returncode == 0, result.stderr
    assert _state(root, home) != before


def test_abort_on_conflict_writes_nothing_on_a_conflict(topics):
    root, home = topics(shared=True)
    before = _state(root, home)
    result = _run(root, "rebase", "-s", "b", "-d", "a",
                  "--abort-on-conflict", home=home)
    assert result.returncode == 1
    assert "topic b" in result.stderr
    assert "keepalive" in result.stderr
    assert _state(root, home) == before


def test_abort_on_conflict_ignores_an_existing_conflict(topics):
    root, home = topics(shared=True)
    assert _run(root, "rebase", "-s", "b", "-d", "a",
                home=home).returncode == 0
    _run(root, "new", "main", "-m", "topic c", home=home)
    (root / "c.txt").write_text("c\n")
    _run(root, "bookmark", "create", "c", "-r", "@", home=home)
    result = _run(root, "rebase", "-r", "c", "-d", "a",
                  "--abort-on-conflict", home=home)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("shared", [False, True])
def test_dry_run_writes_nothing(topics, shared):
    root, home = topics(shared=shared)
    before = _state(root, home)
    result = _run(root, "rebase", "-s", "b", "-d", "a", "--dry-run",
                  home=home)
    assert result.returncode == 0, result.stderr
    assert "Would write 2 commits." in result.stdout
    assert ("New conflicts would appear in 2 commits:" in result.stdout) == shared
    assert _state(root, home) == before


def test_dry_run_with_abort_on_conflict_exits_1_on_a_conflict(topics):
    root, home = topics(shared=True)
    before = _state(root, home)
    result = _run(root, "rebase", "-s", "b", "-d", "a", "--dry-run",
                  "--abort-on-conflict", home=home)
    assert result.returncode == 1
    assert "topic b" in result.stdout
    assert _state(root, home) == before
