"""Tests for `pyjj undo` / `pyjj redo --allow-cross-workspace`.

Since jj 0.46 undo/redo refuse an operation performed in another
workspace unless allowed. That needs operations from two workspaces
with each command run from its own directory *without* `-R`: `-R`
pins the workspace, so the parity harness (which always passes `-R`)
cannot produce a cross-workspace operation at all. These drive the
real CLI as a subprocess instead, like test_bisect_cli.py does.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def cli_env(tmp_path_factory):
    """Scratch HOME plus author identity, like the parity harness sets."""
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        JJ_USER="tester",
        JJ_EMAIL="tester@example.com",
        # Pinned clocks and randomness, like the parity harness: no
        # assertion reads them today, but nothing may depend on the wall
        # clock or an unseeded draw tomorrow.
        JJ_TIMESTAMP="2001-02-03T04:05:06+00:00",
        JJ_OP_TIMESTAMP="2001-02-03T04:05:06+00:00",
        JJ_TZ_OFFSET_MINS="330",
        # No JJ_RANDOMNESS_SEED: one fixed seed mints the same change
        # id for every new commit, turning the repo divergent.
        NO_COLOR="1",
    )
    return env


@pytest.fixture
def two_workspace_repo(tmp_path_factory, cli_env):
    """A repo with a `second` workspace holding one described commit."""
    root = tmp_path_factory.mktemp("repo")
    second = root / "second"

    def run(*args, cwd=root):
        result = subprocess.run(
            [sys.executable, "-m", "pyjj_cli", *args],
            cwd=cwd, env=cli_env, capture_output=True, text=True,
        )
        return result

    assert run("git", "init", ".").returncode == 0
    (root / "base.txt").write_text("base\n")
    assert run("describe", "-m", "base").returncode == 0
    assert run("workspace", "add", "second").returncode == 0
    (second / "late.txt").write_text("late\n")
    assert run("describe", "-m", "second work", cwd=second).returncode == 0
    return root, second, run


def test_undo_refuses_a_cross_workspace_operation(two_workspace_repo):
    root, _second, run = two_workspace_repo
    result = run("undo", cwd=root)
    assert result.returncode != 0
    assert "Refusing to undo operation " in result.stderr
    assert "because it was performed in workspace second" in result.stderr
    assert ("Hint: Use `--allow-cross-workspace` to undo it anyway" in
            result.stderr)


@pytest.mark.covers("undo", "--allow-cross-workspace")
def test_undo_allow_cross_workspace_goes_through(two_workspace_repo):
    root, _second, run = two_workspace_repo
    result = run("undo", "--allow-cross-workspace", cwd=root)
    assert result.returncode == 0, result.stderr


def test_redo_refuses_a_cross_workspace_undo(two_workspace_repo):
    root, second, run = two_workspace_repo
    assert run("undo", cwd=second).returncode == 0
    result = run("redo", cwd=root)
    assert result.returncode != 0
    assert "Refusing to redo operation " in result.stderr
    assert "because it was performed in workspace second" in result.stderr


@pytest.mark.covers("redo", "--allow-cross-workspace")
def test_redo_allow_cross_workspace_goes_through(two_workspace_repo):
    root, second, run = two_workspace_repo
    assert run("undo", cwd=second).returncode == 0
    result = run("redo", "--allow-cross-workspace", cwd=root)
    assert result.returncode == 0, result.stderr


def test_undo_of_workspace_remove_warns(two_workspace_repo):
    """Undoing a removal restores the workspace record, not its files."""
    root, _second, run = two_workspace_repo
    assert run("workspace", "remove", "second", cwd=root).returncode == 0
    result = run("undo", cwd=root)
    assert result.returncode == 0, result.stderr
    assert ("Warning: Undoing a workspace removal restores the workspace, "
            "but does not restore the workspace directory." in result.stderr)
    assert "Run `jj workspace forget` then `jj workspace add`" in result.stderr
