"""Path arguments read from the working directory, as in jj.

Run from `sub/`, `a.txt` names `sub/a.txt`. The parity suite proves
the writing commands bit-identical from a subdirectory
(`test_paths_resolve_from_the_working_directory`); these check what
the reading ones print, which a state comparison cannot see. Expected
text is what jj 0.47.1 prints for the same repository.
"""

import os
import subprocess
import sys

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


@pytest.fixture
def repo(tmp_path):
    home = tmp_path / "home"
    (home / "jj").mkdir(parents=True)
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    env = os.environ.copy()
    env.update(JJ_ENV)
    env["XDG_CONFIG_HOME"] = str(home)

    def run(*args, cwd=root / "sub"):
        return subprocess.run([sys.executable, "-m", "pyjj_cli", *args],
                              capture_output=True, text=True, env=env, cwd=str(cwd))

    assert run("git", "init", cwd=root).returncode == 0
    (root / "sub" / "a.txt").write_text("a\n")
    (root / "top.txt").write_text("t\n")
    assert run("commit", "-m", "base", cwd=root).returncode == 0
    (root / "sub" / "a.txt").write_text("a2\n")
    (root / "top.txt").write_text("t2\n")
    run.root = root
    return run


ONE_FILE = "1 file changed, 1 insertion(+), 1 deletion(-)\n"


def test_a_relative_path_resolves_from_the_working_directory(repo):
    result = repo("diff", "--stat", "a.txt")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "a.txt | 2 +-\n" + ONE_FILE
    assert result.stderr == ""


def test_a_path_can_reach_outside_the_working_directory(repo):
    result = repo("diff", "--stat", "../top.txt")
    assert result.stdout == "../top.txt | 2 +-\n" + ONE_FILE


def test_an_absolute_path_inside_the_workspace_resolves(repo):
    result = repo("diff", "--stat", str(repo.root / "top.txt"))
    assert result.stdout == "../top.txt | 2 +-\n" + ONE_FILE


def test_a_root_relative_path_is_not_read_from_the_root(repo):
    """The bug report's case: from `sub/`, `sub/a.txt` is `sub/sub/a.txt`."""
    result = repo("diff", "--stat", "sub/a.txt")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "0 files changed, 0 insertions(+), 0 deletions(-)\n"
    assert result.stderr == "Warning: No matching entries for paths: sub/a.txt\n"


def test_a_path_outside_the_workspace_is_an_error(repo):
    result = repo("diff", "--stat", "../../outside.txt")
    assert result.returncode == 1
    assert "is not in the repo" in result.stderr


def test_status_names_an_unmatched_path(repo):
    result = repo("status", "nope.txt")
    assert result.returncode == 0, result.stderr
    assert result.stderr == "Warning: No matching entries for paths: nope.txt\n"


def test_split_on_an_unmatched_path_says_the_new_revision_is_empty(repo):
    """jj still splits, as before; what it adds is saying so."""
    result = repo("split", "-m", "first", "nope.txt")
    assert result.returncode == 0, result.stderr
    assert result.stderr.startswith(
        "Warning: No matching entries for paths: nope.txt\n"
        "Warning: No changes have been selected, so the new revision will be empty.\n")


@pytest.mark.parametrize("path", ["nope.txt", "sub/a.txt"])
def test_commit_on_an_unmatched_path_warns(repo, path):
    """Issue 1: the empty commit itself is jj's behaviour; the silence was not."""
    result = repo("commit", "-m", "first", path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == f"Warning: The given paths do not match any file: {path}\n"


def test_commit_on_a_matched_path_does_not_warn(repo):
    result = repo("commit", "-m", "first", "a.txt")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_split_of_every_change_says_the_original_becomes_empty(repo):
    result = repo("split", "-m", "first", "a.txt", "../top.txt")
    assert result.returncode == 0, result.stderr
    assert result.stderr.startswith(
        "Warning: All changes have been selected, so the original revision "
        "will become empty.\n")
