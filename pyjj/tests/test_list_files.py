"""Tests for Commit.list_files(): jj file list [paths] equivalent."""

from pathlib import Path

import pyjj


def test_list_files_returns_every_tracked_path(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    root.joinpath("a.txt").write_text("a\n")
    (root / "dir").mkdir()
    (root / "dir" / "b.txt").write_text("b\n")

    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert set(commit.list_files()) == {"a.txt", "dir/b.txt"}


def test_list_files_paths_restricts_the_same_way_diff_does(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    root.joinpath("a.txt").write_text("a\n")
    (root / "dir").mkdir()
    (root / "dir" / "b.txt").write_text("b\n")

    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert commit.list_files(paths=["a.txt"]) == ["a.txt"]
    assert commit.list_files(paths=["dir"]) == ["dir/b.txt"]
    assert commit.list_files(paths=["no-such-path.txt"]) == []


def test_list_files_does_not_include_directories_themselves(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "dir").mkdir()
    (root / "dir" / "b.txt").write_text("b\n")

    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert "dir" not in commit.list_files()


def test_list_files_includes_symlinks(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    root.joinpath("a.txt").write_text("a\n")
    (root / "link").symlink_to("a.txt")

    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert set(commit.list_files()) == {"a.txt", "link"}


def test_list_files_on_root_commit_is_empty(repo, settings):
    root_commit = repo.resolve_single(settings, "root()")
    assert root_commit.list_files() == []
