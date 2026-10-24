"""`pyjj workspace clean`: remove and forget the workspaces merged into trunk()."""

import json
import os
import subprocess
import sys

import pytest

ENV = {**os.environ, "JJ_USER": "tester", "JJ_EMAIL": "tester@example.com",
       "NO_COLOR": "1", "GIT_EDITOR": "true", "TZ": "UTC"}

# Every workspace here is seconds old, which the default grace keeps.
CLEAN = ("workspace", "clean", "--grace", "0s")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, env=ENV)


def _pyjj(cwd, *args, env=ENV):
    return subprocess.run([sys.executable, "-m", "pyjj_cli", *args], cwd=cwd,
                          capture_output=True, text=True, env=env)


def _ok(cwd, *args, env=ENV):
    result = _pyjj(cwd, *args, env=env)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def work(tmp_path):
    """A clone of a remote whose `main` holds one commit, so trunk() is
    `main@origin`."""
    seed, remote, work = (tmp_path / name for name in ("seed", "remote.git", "work"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _git(seed, "commit", "--allow-empty", "-m", "one")
    _git(seed, "push", "-q", str(remote), "main")
    _ok(tmp_path, "git", "clone", str(remote), str(work))
    return work


def _workspaces(work):
    out = _ok(work, "workspace", "list", "-T", "{{ name }}\n").stdout
    return set(out.split())


def test_removes_an_idle_workspace(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "idle"))
    result = _ok(work, *CLEAN, "--force")
    assert "Removed workspace directory" in result.stdout
    assert not (tmp_path / "idle").exists()
    assert _workspaces(work) == {"default"}


def test_keeps_an_edit_no_snapshot_has_seen(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "dirty"))
    (tmp_path / "dirty" / "new.txt").write_text("unsaved\n")
    result = _ok(work, *CLEAN, "--force")
    assert "Nothing changed." in result.stderr
    assert (tmp_path / "dirty" / "new.txt").read_text() == "unsaved\n"
    assert _workspaces(work) == {"default", "dirty"}


def test_keeps_committed_unmerged_work(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "wip"))
    (tmp_path / "wip" / "a.txt").write_text("a\n")
    _ok(tmp_path / "wip", "commit", "-m", "wip")
    _ok(work, "workspace", "add", str(tmp_path / "described"))
    _ok(tmp_path / "described", "describe", "-m", "plan")
    _ok(work, *CLEAN, "--force")
    assert _workspaces(work) == {"default", "wip", "described"}


def test_removes_work_once_trunk_contains_it(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "feat"))
    (tmp_path / "feat" / "a.txt").write_text("a\n")
    _ok(tmp_path / "feat", "commit", "-m", "feat")
    _ok(work, *CLEAN, "--force")
    assert "feat" in _workspaces(work)
    _ok(work, "bookmark", "set", "main", "-r", "feat@-")
    _ok(work, "git", "push", "--bookmark", "main")
    _ok(work, *CLEAN, "--force")
    assert _workspaces(work) == {"default"}
    assert not (tmp_path / "feat").exists()


def test_never_removes_the_current_or_the_repository_workspace(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "here"))
    result = _ok(tmp_path / "here", *CLEAN, "--force")
    assert "Nothing changed." in result.stderr
    assert "Warning" not in result.stderr
    assert _workspaces(work) == {"default", "here"}


def test_without_force_it_only_lists(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "idle"))
    result = _ok(work, *CLEAN)
    assert "Would remove workspace idle" in result.stdout
    assert "--force" in result.stderr
    assert (tmp_path / "idle").exists()
    assert _workspaces(work) == {"default", "idle"}


def test_forgets_a_workspace_whose_directory_is_gone(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "gone"))
    (tmp_path / "gone" / "a.txt").write_text("a\n")
    _ok(tmp_path / "gone", "commit", "-m", "unmerged")
    subprocess.run(["rm", "-rf", str(tmp_path / "gone")], check=True)
    result = _ok(work, *CLEAN, "--force")
    assert "Forgot workspace gone (directory missing)" in result.stdout
    assert _workspaces(work) == {"default"}
    assert "unmerged" in _descriptions(work)


def _head_op(work):
    return _ok(work, "op", "log", "--no-graph", "--limit", "1", "-T", "{{ id }}").stdout


def test_listing_writes_no_operation(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "idle"))
    _ok(work, "workspace", "add", str(tmp_path / "dirty"))
    (tmp_path / "dirty" / "new.txt").write_text("unsaved\n")
    before = _head_op(work)
    _ok(work, *CLEAN)
    _ok(work, *CLEAN, "--format", "json")
    assert _head_op(work) == before


def test_json_reports_every_workspace(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "idle"))
    _ok(work, "workspace", "add", str(tmp_path / "wip"))
    _ok(tmp_path / "wip", "describe", "-m", "wip")
    result = _ok(work, *CLEAN, "--format", "json")
    report = json.loads(result.stdout)
    assert report["applied"] is False
    actions = {w["name"]: (w["action"], w["reason"]) for w in report["workspaces"]}
    assert actions == {
        "default": ("keep", "current workspace"),
        "idle": ("remove", "merged"),
        "wip": ("keep", "unmerged"),
    }
    forced = json.loads(_ok(work, *CLEAN, "--format", "json", "--force").stdout)
    assert forced["applied"] is True
    assert _workspaces(work) == {"default", "wip"}


def test_removes_a_squash_merged_workspace(work, tmp_path):
    feat = tmp_path / "feat"
    _ok(work, "workspace", "add", str(feat))
    (feat / "a.txt").write_text("a\n")
    _ok(feat, "commit", "-m", "one")
    (feat / "b.txt").write_text("b\n")
    _ok(feat, "commit", "-m", "two")
    (work / "a.txt").write_text("a\n")
    (work / "b.txt").write_text("b\n")
    _ok(work, "commit", "-m", "squashed")
    (work / "c.txt").write_text("c\n")
    _ok(work, "commit", "-m", "later trunk work")
    _ok(work, "bookmark", "set", "main", "-r", "@-")
    _ok(work, "git", "push", "--bookmark", "main")
    result = _ok(work, *CLEAN)
    assert "Would remove workspace feat" in result.stdout
    assert "(changes in trunk)" in result.stdout


def test_partly_merged_work_is_kept(work, tmp_path):
    feat = tmp_path / "feat"
    _ok(work, "workspace", "add", str(feat))
    (feat / "a.txt").write_text("a\n")
    (feat / "b.txt").write_text("b\n")
    _ok(feat, "commit", "-m", "both")
    (work / "a.txt").write_text("a\n")
    _ok(work, "commit", "-m", "only a")
    _ok(work, "bookmark", "set", "main", "-r", "@-")
    _ok(work, "git", "push", "--bookmark", "main")
    _ok(work, *CLEAN, "--force")
    assert "feat" in _workspaces(work)


def test_older_than_removes_idle_unmerged_work(work, tmp_path):
    old, fresh = tmp_path / "old", tmp_path / "fresh"
    for path in (old, fresh):
        _ok(work, "workspace", "add", str(path))
        (path / "a.txt").write_text("a\n")
    _ok(old, "describe", "-m", "ancient",
        env={**ENV, "JJ_TIMESTAMP": "2001-02-03T04:05:06+00:00"})
    _ok(fresh, "describe", "-m", "recent")
    _ok(work, *CLEAN, "--force")
    assert _workspaces(work) == {"default", "old", "fresh"}

    dry = _ok(work, *CLEAN, "--older-than", "30d")
    assert "Would remove workspace old" in dry.stdout
    assert "idle since 2001-02-03" in dry.stdout
    assert "fresh" not in dry.stdout

    _ok(work, *CLEAN, "--older-than", "30d", "--force")
    assert _workspaces(work) == {"default", "fresh"}
    assert not old.exists()
    log = _ok(work, "log", "--no-graph", "-r", "all()", "-T", "{{ description }}").stdout
    assert "ancient" in log


def test_older_than_counts_an_unrecorded_edit_as_fresh(work, tmp_path):
    old = tmp_path / "old"
    _ok(work, "workspace", "add", str(old))
    (old / "a.txt").write_text("a\n")
    _ok(old, "describe", "-m", "ancient",
        env={**ENV, "JJ_TIMESTAMP": "2001-02-03T04:05:06+00:00"})
    (old / "a.txt").write_text("touched\n")
    _ok(work, *CLEAN, "--older-than", "30d", "--force")
    assert (old / "a.txt").read_text() == "touched\n"


def test_older_than_rejects_a_bad_duration(work):
    result = _pyjj(work, *CLEAN, "--older-than", "30 days")
    assert result.returncode == 2
    assert "invalid duration" in result.stderr


def _descriptions(work):
    out = _ok(work, "log", "--no-graph", "-r", "all()", "-T",
              "{{ description.splitlines()[0] if description else '-' }}\n").stdout
    return out.splitlines()


def test_rewritten_unmerged_workspace_is_kept_without_a_spurious_commit(work, tmp_path):
    feat = tmp_path / "feat"
    _ok(work, "workspace", "add", str(feat))
    (feat / "a.txt").write_text("a\n")
    _ok(feat, "commit", "-m", "feat")
    _ok(work, "describe", "-r", "feat@-", "-m", "rewritten")
    before = _descriptions(work)
    result = _pyjj(work, *CLEAN, "--force")
    assert result.returncode == 0, result.stderr
    assert "feat" in _workspaces(work)
    assert _descriptions(work) == before


def _stale_merged_feat(work, tmp_path):
    feat = tmp_path / "feat"
    _ok(work, "workspace", "add", str(feat))
    (feat / "a.txt").write_text("a\n")
    _ok(feat, "commit", "-m", "feat")
    (work / "b.txt").write_text("b\n")
    _ok(work, "commit", "-m", "base")
    _ok(work, "rebase", "-r", "feat@-", "-d", "@-")
    _ok(work, "bookmark", "set", "main", "-r", "feat@-")
    _ok(work, "git", "push", "--bookmark", "main")
    return feat


def test_stale_merged_workspace_is_removed(work, tmp_path):
    feat = _stale_merged_feat(work, tmp_path)
    status = _pyjj(feat, "status")
    assert "stale" in status.stdout + status.stderr
    _ok(work, *CLEAN, "--force")
    assert _workspaces(work) == {"default"}
    assert not feat.exists()


def test_stale_workspace_with_unrecorded_edits_is_kept(work, tmp_path):
    feat = _stale_merged_feat(work, tmp_path)
    (feat / "a.txt").write_text("edited after the rebase\n")
    report = json.loads(_ok(work, *CLEAN, "--format", "json", "--force").stdout)
    actions = {w["name"]: (w["action"], w["reason"]) for w in report["workspaces"]}
    assert actions["feat"] == ("keep", "unrecorded changes")
    assert (feat / "a.txt").read_text() == "edited after the rebase\n"


def test_rewritten_merged_workspace_is_removed(work, tmp_path):
    feat = tmp_path / "feat"
    _ok(work, "workspace", "add", str(feat))
    (feat / "a.txt").write_text("a\n")
    _ok(feat, "commit", "-m", "feat")
    _ok(work, "describe", "-r", "feat@-", "-m", "rewritten")
    _ok(work, "bookmark", "set", "main", "-r", "feat@-")
    _ok(work, "git", "push", "--bookmark", "main")
    result = _pyjj(work, *CLEAN, "--force")
    assert result.returncode == 0, result.stderr
    assert _workspaces(work) == {"default"}


def _actions(work, *extra):
    report = json.loads(_ok(work, *extra, "--format", "json", "--force").stdout)
    return {w["name"]: (w["action"], w["reason"]) for w in report["workspaces"]}


def test_default_grace_keeps_a_fresh_workspace(work, tmp_path):
    _ok(work, "workspace", "add", str(tmp_path / "fresh"))
    action, reason = _actions(work, "workspace", "clean")["fresh"]
    assert action == "keep"
    assert "within --grace" in reason
    assert (tmp_path / "fresh").exists()


@pytest.fixture
def running():
    procs = []

    def start(argv, cwd):
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE)
        procs.append(proc)
        assert proc.stdout is not None
        proc.stdout.readline()
        return proc

    yield start
    for proc in procs:
        proc.kill()
        proc.wait()


def test_keeps_a_workspace_a_process_runs_in(work, tmp_path, running):
    idle = tmp_path / "idle"
    _ok(work, "workspace", "add", str(idle))
    proc = running(["sh", "-c", "echo ready; exec sleep 60"], idle)
    action, reason = _actions(work, *CLEAN)["idle"]
    assert (action, reason) == ("keep", f"in use by pid {proc.pid} (sleep)")
    assert idle.exists()


def test_keeps_a_workspace_holding_an_open_file(work, tmp_path, running):
    idle = tmp_path / "idle"
    _ok(work, "workspace", "add", str(idle))
    held = idle / ".jj" / "working_copy" / "tree_state"
    assert held.exists()
    holder = ("import sys, time; f = open(sys.argv[1]); print('ready', flush=True); "
              "time.sleep(60)")
    proc = running([sys.executable, "-c", holder, str(held)], tmp_path)
    action, reason = _actions(work, *CLEAN)["idle"]
    assert action == "keep"
    assert reason.startswith(f"in use by pid {proc.pid}")
    assert idle.exists()
