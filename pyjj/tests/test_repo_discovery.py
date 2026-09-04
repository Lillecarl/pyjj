"""A command must find its repository from a subdirectory.

`jj` walks up from the current directory looking for a `.jj`, so every
command works anywhere inside a workspace and not only at its root
(`find_workspace_dir` in `cli/src/cli_util.rs`). `-R` skips the search
and names the workspace outright.

Driven as a subprocess, because the search reads the process's own
working directory.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _needs_jj():
    if not (os.environ.get("PYJJ_PARITY_JJ") or shutil.which("jj")):
        pytest.skip("no jj binary on PATH")


@pytest.fixture
def nested_repo(tmp_path_factory):
    """A workspace with a `sub/deep/` directory, and a sibling directory
    that is in no workspace at all."""
    base = tmp_path_factory.mktemp("base")
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        JJ_USER="tester",
        JJ_EMAIL="tester@example.com",
        NO_COLOR="1",
    )
    jj = os.environ.get("PYJJ_PARITY_JJ") or "jj"
    root = base / "repo"
    root.mkdir()
    result = subprocess.run([jj, "git", "init", "."], cwd=root, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "deep" / "f.txt").write_text("hi\n")
    outside = base / "outside"
    outside.mkdir()
    return root, outside, env


def run_pyjj(cwd, env, *args):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def test_finds_the_repo_from_a_subdirectory(nested_repo):
    """The changed file is named relative to the current directory, as
    jj names it -- so this checks the search and the spelling at once."""
    root, _outside, env = nested_repo
    result = run_pyjj(root / "sub" / "deep", env, "--no-pager", "status")
    assert result.returncode == 0, result.stderr
    assert "A f.txt" in result.stdout


def test_finds_the_repo_from_the_root_too(nested_repo):
    root, _outside, env = nested_repo
    result = run_pyjj(root, env, "--no-pager", "status")
    assert result.returncode == 0, result.stderr


def test_a_util_command_finds_it_as_well(nested_repo):
    """`util backend name` loads the workspace without the shared
    `_load()` path, so it needs the search of its own."""
    root, _outside, env = nested_repo
    result = run_pyjj(root / "sub", env, "--no-pager", "util", "backend", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "git"


def test_outside_any_workspace_still_fails(nested_repo):
    """A search that finds nothing falls back to the current directory,
    which fails with the same error as before."""
    _root, outside, env = nested_repo
    result = run_pyjj(outside, env, "--no-pager", "status")
    assert result.returncode == 1
    assert "no Jujutsu repo" in result.stderr


def test_dash_R_wins_over_the_search(nested_repo):
    """`-R` names the workspace outright, from anywhere."""
    root, outside, env = nested_repo
    result = run_pyjj(outside, env, "--no-pager", "-R", str(root), "status")
    assert result.returncode == 0, result.stderr
    # The path is still spelled relative to the current directory, which
    # is outside the workspace, so it walks back out with `..` -- jj
    # prints exactly this.
    assert f"A ../{root.name}/sub/deep/f.txt" in result.stdout


def test_dash_R_does_not_search_upward(nested_repo):
    """jj resolves `-R` and fails if that exact path is not a workspace;
    it does not walk up from there."""
    root, _outside, env = nested_repo
    result = run_pyjj(root, env, "--no-pager", "-R", str(root / "sub"), "status")
    assert result.returncode == 1
