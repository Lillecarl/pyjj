"""Tests for the executable bit: Commit.is_executable(), Transaction.set_executable(),
and diff()'s "executable" status for mode-only changes.
"""

import os
import stat
from pathlib import Path

import pytest

import pyjj


def test_new_file_is_not_executable_by_default(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert commit.is_executable("a.txt") is False


def test_is_executable_none_for_nonexistent_and_directory_paths(workspace, repo, settings):
    Path(workspace.workspace_root, "dir").mkdir()
    Path(workspace.workspace_root, "dir", "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert commit.is_executable("no-such-file.txt") is None
    assert commit.is_executable("dir") is None


def test_set_executable_flips_bit_without_changing_content(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.set_executable(commit, "a.txt", True)
    builder.set_description("chmod +x a.txt")
    new_commit = builder.write(repo)
    tx.set_wc_commit("default", new_commit.id)
    tx.rebase_descendants()
    tx.commit("chmod")

    assert new_commit.is_executable("a.txt") is True
    assert new_commit.read_file("a.txt") == commit.read_file("a.txt")


def test_set_executable_back_to_false(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.set_executable(commit, "a.txt", True)
    executable_commit = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("chmod +x")

    tx2 = repo2.start_transaction(settings)
    builder2 = tx2.set_executable(executable_commit, "a.txt", False)
    normal_commit = builder2.write(repo2)
    tx2.rebase_descendants()
    tx2.commit("chmod -x")

    assert normal_commit.is_executable("a.txt") is False


def test_set_executable_on_nonexistent_path_raises(workspace, repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.set_executable(wc_commit, "no-such-file.txt", True)


def test_diff_reports_mode_only_change_as_executable(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.set_executable(commit, "a.txt", True)
    new_commit = builder.write(repo)
    tx.rebase_descendants()
    tx.commit("chmod +x")

    entries = commit.diff(new_commit)
    assert len(entries) == 1
    assert entries[0].path == "a.txt"
    assert entries[0].status == "executable"
    assert entries[0].executable is True


def test_diff_executable_field_reflects_current_state(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    diff_from_root = repo.resolve_single(settings, "root()").diff(commit)
    added = next(e for e in diff_from_root if e.path == "a.txt")
    assert added.status == "added"
    assert added.executable is False


def test_snapshot_picks_up_executable_bit_from_disk(workspace, repo, settings):
    """Mirrors lib/tests/test_local_working_copy_executable_bit.rs's
    test_exec_bit_snapshot: chmod'ing a file on disk (outside of
    Transaction.set_executable()) and snapshotting should pick up the bit.
    """
    path = Path(workspace.workspace_root, "file")
    path.write_text("initial content")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    assert commit.is_executable("file") is False

    os.chmod(path, 0o755)
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    assert commit.is_executable("file") is True


def test_check_out_writes_executable_bit_to_disk(workspace, repo, settings):
    """Mirrors test_exec_bit_checkout: checking out a commit whose file is
    marked executable/non-executable should update the real filesystem mode,
    not just the in-repo tree metadata.
    """
    path = Path(workspace.workspace_root, "file")
    path.write_text("initial content")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.set_executable(commit, "file", True)
    executable_commit = builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("chmod +x")

    workspace.check_out(repo, repo.get_commit(executable_commit.id))
    mode = os.stat(path).st_mode
    assert bool(mode & stat.S_IXUSR) is True

    tx2 = repo.start_transaction(settings)
    builder2 = tx2.set_executable(executable_commit, "file", False)
    normal_commit = builder2.write(repo)
    tx2.rebase_descendants()
    repo = tx2.commit("chmod -x")

    workspace.check_out(repo, repo.get_commit(normal_commit.id))
    mode = os.stat(path).st_mode
    assert bool(mode & stat.S_IXUSR) is False
