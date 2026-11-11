"""A published trunk moves only forward unless `--allow-nonff` says so.

`main` is protected once `main@origin` exists, so every test pushes it
first. Each refusal also checks that no operation was written.
"""

import os
import subprocess
import sys
import textwrap

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


@pytest.fixture
def repo(tmp_path):
    home = tmp_path / "home"
    (home / "jj").mkdir(parents=True)
    root = tmp_path / "repo"
    root.mkdir()
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    env = os.environ.copy()
    env.update(JJ_ENV)
    env["XDG_CONFIG_HOME"] = str(home)

    class Repo:
        path = root
        remote = bare

        def run(self, *args):
            return subprocess.run(
                [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
                capture_output=True, text=True, env=env, cwd=str(root),
            )

        def ok(self, *args):
            result = self.run(*args)
            assert result.returncode == 0, result.stderr
            return result.stdout

        def commit_id(self, rev):
            return self.ok("log", "-r", rev, "--no-graph", "-T", "{{ commit_id }}").strip()

        def op_ids(self):
            return self.ok("op", "log", "--no-graph", "-T", "{{ id }}\n")

        def config(self, text):
            (home / "jj" / "config.toml").write_text(text)

    r = Repo()
    r.ok("git", "init")
    for name in ("one", "two"):
        (root / f"{name}.txt").write_text(f"{name}\n")
        r.ok("commit", "-m", name)
    r.ok("bookmark", "create", "main", "-r", "@--")
    r.ok("git", "remote", "add", "origin", str(bare))
    r.ok("git", "push", "--bookmark", "main")
    return r


def refused(result, how="move backwards or sideways"):
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"Refusing to {how} fast-forward-only bookmark main" in result.stderr
    assert "Hint: Use --allow-nonff to allow it." in result.stderr


def test_moving_main_forward_is_allowed(repo):
    repo.ok("bookmark", "set", "main", "-r", "@-")
    assert repo.commit_id("main") == repo.commit_id("@-")


def test_moving_main_backwards_is_refused_even_with_allow_backwards(repo):
    before = repo.op_ids()
    refused(repo.run("bookmark", "set", "main", "-r", "@---", "--allow-backwards"))
    assert repo.op_ids() == before
    repo.ok("--allow-nonff", "bookmark", "set", "main", "-r", "@---", "--allow-backwards")
    assert repo.commit_id("main") == repo.commit_id("@---")


def test_deleting_main_is_refused(repo):
    refused(repo.run("bookmark", "delete", "main"), how="delete")
    repo.ok("bookmark", "delete", "main", "--allow-nonff")


def test_forgetting_main_is_refused_without_a_false_success_line(repo):
    result = repo.run("bookmark", "forget", "main")
    refused(result, how="delete")
    assert "Forgot" not in result.stdout


def test_abandoning_mains_commit_is_refused(repo):
    """`abandon` deletes the abandoned commit's bookmarks, as jj's does."""
    refused(repo.run("--ignore-immutable", "abandon", "main"), how="delete")


def test_rewriting_mains_commit_is_refused(repo):
    """A rewrite in place gives `main` a new commit id that does not
    descend from the published one: sideways."""
    refused(repo.run("--ignore-immutable", "describe", "main", "-m", "rewritten"))


def test_undoing_a_forward_move_is_refused(repo):
    repo.ok("bookmark", "set", "main", "-r", "@-")
    refused(repo.run("undo"))
    repo.ok("undo", "--allow-nonff")


def test_dry_run_reports_the_refusal(repo):
    before = repo.op_ids()
    refused(repo.run("--ignore-immutable", "abandon", "main", "--dry-run"), how="delete")
    assert repo.op_ids() == before


def test_an_unpublished_main_is_unconstrained(tmp_path, repo):
    repo.ok("git", "remote", "remove", "origin")
    repo.ok("bookmark", "set", "main", "-r", "@---", "--allow-backwards")


def test_config_names_the_protected_bookmarks(repo):
    repo.config('[pyjj]\nfast-forward-bookmarks = []\n')
    repo.ok("bookmark", "set", "main", "-r", "@---", "--allow-backwards")


def test_a_fetch_follows_the_remote_backwards(repo):
    """A rewritten remote trunk is the remote's decision, not this
    command's: fetch adopts it."""
    older = repo.commit_id("main")
    repo.ok("bookmark", "set", "main", "-r", "@-")
    repo.ok("git", "push", "--bookmark", "main")
    subprocess.run(["git", "-C", str(repo.remote), "update-ref", "refs/heads/main", older],
                   check=True)
    repo.ok("git", "fetch")
    assert repo.commit_id("main") == older


def test_a_script_is_refused_too(repo):
    script = textwrap.dedent("""
        try:
            with repo.atomic("move main") as tx:
                tx.bookmark("main", "@---")
        except pyjj.NonFastForwardError as e:
            print("refused:", e.refused)
        with repo.atomic("move main", allow_nonff=True) as tx:
            tx.bookmark("main", "@---")
        print("moved")
    """)
    out = repo.ok("python", "-c", script)
    assert out == "refused: [('main', 'move backwards or sideways')]\nmoved\n"
    assert repo.commit_id("main") == repo.commit_id("@---")
