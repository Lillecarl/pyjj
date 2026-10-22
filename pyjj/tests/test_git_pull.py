"""`pyjj git pull`: fetch, then move an idle working copy onto the new trunk."""

import os
import subprocess
import sys

import pytest

ENV = {**os.environ, "JJ_USER": "tester", "JJ_EMAIL": "tester@example.com",
       "NO_COLOR": "1", "GIT_EDITOR": "true"}


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, env=ENV)


def _pyjj(cwd, *args):
    return subprocess.run([sys.executable, "-m", "pyjj_cli", *args], cwd=cwd,
                          capture_output=True, text=True, env=ENV)


@pytest.fixture
def upstream(tmp_path):
    """A seed repo and a bare remote, both holding `main` at commit one,
    with a clone of the remote in `work`."""
    seed, remote, work = (tmp_path / name for name in ("seed", "remote.git", "work"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _git(seed, "commit", "--allow-empty", "-m", "one")
    _git(seed, "push", "-q", str(remote), "main")
    assert _pyjj(tmp_path, "git", "clone", str(remote), str(work)).returncode == 0

    def advance(message):
        _git(seed, "commit", "--allow-empty", "-m", message)
        _git(seed, "push", "-q", str(remote), "main")

    return work, advance


def _log(work):
    return _pyjj(work, "log", "--no-graph", "-T", "{{ description }}|{{ bookmarks | join(" ") }}\n").stdout


def test_up_to_date(upstream):
    work, _ = upstream
    result = _pyjj(work, "git", "pull")
    assert result.returncode == 0
    assert "Already up to date" in result.stderr


def test_fast_forwards_idle_working_copy(upstream):
    work, advance = upstream
    advance("two")
    result = _pyjj(work, "git", "pull")
    assert result.returncode == 0, result.stderr
    assert "Fast-forwarded main" in result.stderr
    log = _log(work).splitlines()
    assert log[0].startswith("(no description set)"), log
    assert log[1].startswith("two|main"), log


def test_keeps_working_copy_with_changes(upstream):
    work, advance = upstream
    assert _pyjj(work, "describe", "-m", "my work").returncode == 0
    advance("two")
    result = _pyjj(work, "git", "pull")
    assert result.returncode == 1
    assert "cannot pull" in result.stderr
    assert "my work" in _log(work)
    assert "two|main" in _log(work)
