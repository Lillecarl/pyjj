"""Tests for Workspace.snapshot()/check_out(): syncing the physical working
copy with the commit graph, and Commit.diff() for inspecting the result.
"""

import os
from pathlib import Path

import pyjj


def test_snapshot_with_no_changes_keeps_same_wc_commit(workspace, repo, settings, wc_commit):
    new_repo, stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")
    assert new_wc.id == wc_commit.id
    assert stats["untracked_paths"] == 0
    # `jj util snapshot` reports exactly this bit.
    assert stats["changed"] is False


def test_snapshot_reports_that_it_changed_something(workspace, repo, settings,
                                                    wc_commit):
    Path(workspace.workspace_root, "moved.txt").write_text("moved\n")
    _new_repo, stats = workspace.snapshot(settings)
    assert stats["changed"] is True


def test_snapshot_picks_up_new_file(workspace, repo, settings, wc_commit):
    Path(workspace.workspace_root, "hello.txt").write_text("hi\n")

    new_repo, _stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")

    assert new_wc.id != wc_commit.id
    assert new_wc.change_id == wc_commit.change_id  # same wc commit, rewritten


def test_snapshot_detects_rapid_same_millisecond_changes(workspace, repo, settings, wc_commit):
    """Mirrors test_local_working_copy.rs's test_snapshot_racy_timestamps:
    file modifications must be detected even when they happen within the
    same millisecond as the previously recorded working-copy state (jj
    can't rely on mtime granularity alone to notice a change).
    """
    path = Path(workspace.workspace_root, "file")
    for i in range(30):
        path.write_text(f"contents {i}")
        repo, _ = workspace.snapshot(settings)
        commit = repo.resolve_single(settings, "@")
        assert commit.read_file("file") == f"contents {i}".encode()


def test_diff_reports_added_file(workspace, repo, settings, wc_commit):
    Path(workspace.workspace_root, "hello.txt").write_text("hi\n")
    new_repo, _stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")

    entries = wc_commit.diff(new_wc)
    assert len(entries) == 1
    assert entries[0].path == "hello.txt"
    assert entries[0].status == "added"


def test_diff_reports_modified_and_removed(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("v1\n")
    (root / "b.txt").write_text("keep me\n")
    repo_after_add, _ = workspace.snapshot(settings)
    before = repo_after_add.resolve_single(settings, "@")

    (root / "a.txt").write_text("v2\n")
    (root / "b.txt").unlink()
    repo_after_edit, _ = workspace.snapshot(settings)
    after = repo_after_edit.resolve_single(settings, "@")

    entries = {e.path: e.status for e in before.diff(after)}
    assert entries == {"a.txt": "modified", "b.txt": "removed"}


def test_diff_paths_restricts_to_matching_files(workspace, repo, settings, wc_commit):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("a\n")
    (root / "dir").mkdir()
    (root / "dir" / "b.txt").write_text("b\n")
    new_repo, _stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")

    all_entries = wc_commit.diff(new_wc)
    assert {e.path for e in all_entries} == {"a.txt", "dir/b.txt"}

    filtered = wc_commit.diff(new_wc, paths=["a.txt"])
    assert {e.path for e in filtered} == {"a.txt"}

    dir_filtered = wc_commit.diff(new_wc, paths=["dir"])
    assert {e.path for e in dir_filtered} == {"dir/b.txt"}

    no_match = wc_commit.diff(new_wc, paths=["no-such-path.txt"])
    assert no_match == []


def test_diff_with_copies_paths_restricts_to_matching_files(workspace, repo, settings, wc_commit):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("a\n")
    (root / "b.txt").write_text("b\n")
    new_repo, _stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")

    filtered = wc_commit.diff_with_copies(new_wc, paths=["a.txt"])
    assert {e.path for e in filtered} == {"a.txt"}


def test_check_out_round_trips_a_symlink(workspace, repo, settings, wc_commit):
    root = Path(workspace.workspace_root)
    (root / "target.txt").write_text("hello\n")
    (root / "link").symlink_to("target.txt")
    repo, _ = workspace.snapshot(settings)
    commit_with_link = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [commit_with_link.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")

    (root / "link").unlink()
    repo, _ = workspace.snapshot(settings)
    assert not repo.resolve_single(settings, "@").file_exists("link")

    workspace.check_out(repo, commit_with_link)
    assert (root / "link").is_symlink()
    assert os.readlink(root / "link") == "target.txt"


def test_check_out_replaces_a_file_with_a_directory_and_back(workspace, repo, settings, wc_commit):
    root = Path(workspace.workspace_root)
    (root / "a").write_text("a is a file\n")
    repo, _ = workspace.snapshot(settings)
    commit_file = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [commit_file.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")

    (root / "a").unlink()
    (root / "a").mkdir()
    (root / "a" / "nested.txt").write_text("now a directory\n")
    repo, _ = workspace.snapshot(settings)
    commit_dir = repo.resolve_single(settings, "@")
    assert commit_dir.file_exists("a/nested.txt")

    workspace.check_out(repo, commit_file)
    assert (root / "a").is_file()
    assert (root / "a").read_text() == "a is a file\n"


def test_check_out_does_not_write_through_a_directory_symlink_escaping_the_workspace(
    workspace, repo, settings
):
    """Security-relevant behavior, mirrors
    lib/tests/test_local_working_copy.rs's
    test_check_out_existing_directory_symlink: if a path component
    (`parent/`) is a symlink pointing outside the workspace, check_out()
    must not follow it to write files through it -- it should skip those
    paths instead of escaping the workspace root.
    """
    root = Path(workspace.workspace_root)
    (root / "parent").mkdir()
    (root / "parent" / "escaped1").write_text("contents")
    (root / "parent" / "escaped2").write_text("contents")
    repo, _ = workspace.snapshot(settings)
    commit_with_files = repo.resolve_single(settings, "@")

    # Clear the working copy back to empty so `parent/` is removed from disk.
    root_id = pyjj.CommitId("0" * 40)
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [root_id])
    empty = builder.write(repo)
    tx.set_wc_commit("default", empty.id)
    tx.rebase_descendants()
    repo = tx.commit("clear")
    workspace.check_out(repo, empty)
    assert not (root / "parent").exists()

    # Recreate `parent` as a symlink escaping the workspace root, then check
    # out the commit whose tree wants to write under `parent/`.
    os.symlink("..", root / "parent")
    commit_with_files = repo.get_commit(commit_with_files.id)
    stats = workspace.check_out(repo, commit_with_files)

    assert stats["skipped_files"] == 2
    outside = root.parent
    assert not (outside / "escaped1").exists()
    assert not (outside / "escaped2").exists()


def test_check_out_skips_a_file_replaced_with_a_directory_without_failing(
    workspace, repo, settings, wc_commit
):
    """Mirrors test_check_out_existing_file_replaced_with_directory:
    check_out() doesn't fail if a target path was replaced with a real
    directory on disk out-of-band -- it just skips that path.
    """
    root = Path(workspace.workspace_root)
    (root / "file").write_text("0")
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    (root / "file").write_text("1")
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    workspace.check_out(repo, commit1)
    (root / "file").unlink()
    (root / "file").mkdir()

    stats = workspace.check_out(repo, commit2)
    assert stats["skipped_files"] == 1
    assert (root / "file").is_dir()


def test_check_out_writes_target_commits_tree_to_disk(workspace, repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("child")
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    new_repo = tx.commit("advance wc")

    stats = workspace.check_out(new_repo, child)
    assert isinstance(stats, dict)
    assert new_repo.resolve_single(settings, "@").id == child.id


def test_reset_does_not_touch_files_on_disk(workspace, repo, settings, wc_commit):
    """Workspace.reset() only re-syncs tracked-file-state bookkeeping to a
    commit's tree -- unlike check_out(), it must never write to the
    filesystem, regardless of what the target commit's tree contains.
    """
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("v1\n")
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [commit1.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("v2\n")
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    (root / "a.txt").write_text("unrelated external content\n")
    workspace.reset(repo, repo.get_commit(commit2.id))
    assert (root / "a.txt").read_text() == "unrelated external content\n"

    # check_out(), by contrast, does overwrite the file for a genuinely
    # different target tree.
    workspace.check_out(repo, repo.get_commit(commit1.id))
    assert (root / "a.txt").read_text() == "v1\n"


def test_reset_lets_a_matching_snapshot_be_a_clean_no_op(workspace, repo, settings):
    """The realistic use case (mirroring the CLI's own
    `import_git_head`): disk genuinely already matches the target commit
    (as if some other tool wrote it), so reset() just needs to stop jj
    considering its recorded state stale -- a subsequent snapshot() should
    see no changes and create no new operation.
    """
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("v1\n")
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [commit1.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("v2\n")
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    workspace.reset(repo, repo.get_commit(commit2.id))
    op_before = repo.operation.id
    new_repo, _stats = workspace.snapshot(settings)
    assert new_repo.operation.id == op_before
