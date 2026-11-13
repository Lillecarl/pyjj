"""`pyjj workspace update-stale` recovers the state it is named for.

Another workspace rewrites an ancestor of this one's `@`, which leaves
this one stale. Every command refuses a stale working copy, and
`update-stale` used to as well, because it took the same snapshot first.
The parity suite cannot reach this: its harness runs each command from
the primary workspace.
"""

import os
import subprocess
import sys

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


@pytest.fixture
def stale(tmp_path):
    home = tmp_path / "home"
    (home / "jj").mkdir(parents=True)
    root, second = tmp_path / "repo", tmp_path / "second"
    root.mkdir()
    env = os.environ.copy()
    env.update(JJ_ENV)
    env["XDG_CONFIG_HOME"] = str(home)

    def run(cwd, *args):
        return subprocess.run([sys.executable, "-m", "pyjj_cli", *args],
                              capture_output=True, text=True, env=env, cwd=str(cwd))

    def ok(cwd, *args):
        result = run(cwd, *args)
        assert result.returncode == 0, result.stderr
        return result

    ok(root, "git", "init")
    (root / "base.txt").write_text("base\n")
    ok(root, "commit", "-m", "base")
    ok(root, "workspace", "add", "--name", "second", "-r", "@-", str(second))
    # Not snapshotted yet: the edit only exists on disk in `second`.
    (second / "edit.txt").write_text("unsaved\n")
    # The bug report's shape: content squashed into an ancestor of
    # `second`'s `@`. A description-only rewrite would not do: a working
    # copy whose tree still matches counts as fresh.
    (root / "base.txt").write_text("base, amended\n")
    ok(root, "squash", "--into", "@-", "-m", "base rewritten")
    run.ok = ok
    run.second = second
    return run


def test_update_stale_recovers_and_keeps_unsaved_edits(stale):
    second = stale.second
    refused = stale(second, "status")
    assert refused.returncode != 0
    assert "stale" in refused.stderr

    result = stale.ok(second, "workspace", "update-stale")
    assert result.stderr.startswith("Updated working copy to fresh commit "), result.stderr

    status = stale.ok(second, "status")
    assert "base rewritten" in status.stdout
    # As in jj 0.47.1: the unsaved edit is snapshotted at the stale
    # operation, so merging that with the squash leaves `@`'s change
    # divergent. The fresh `@` and the files on disk follow the squash;
    # the edit survives in the sibling.
    change = stale.ok(second, "log", "-r", "@", "--no-graph",
                      "-T", "{{ change_id }}").stdout.strip()
    sibling = stale.ok(second, "file", "list", "-r", f"change_id({change}) ~ @")
    assert "edit.txt" in sibling.stdout
    assert "edit.txt" not in stale.ok(second, "file", "list").stdout


def test_update_stale_on_a_fresh_workspace_changes_nothing(stale):
    second = stale.second
    stale.ok(second, "workspace", "update-stale")
    again = stale.ok(second, "workspace", "update-stale")
    assert again.stderr == "Attempted recovery, but the working copy is not stale.\n"
