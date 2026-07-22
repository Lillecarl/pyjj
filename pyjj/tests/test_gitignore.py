"""Tests that Workspace.snapshot() respects per-directory .gitignore files,
same as `jj status`/`jj diff` -- see checkout.rs's docs for what's still
not wired up (`.git/info/exclude`, global `core.excludesFile`).
"""

from pathlib import Path


def test_gitignored_file_is_not_tracked(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / ".gitignore").write_text("ignored.txt\n")
    (root / "ignored.txt").write_text("should be ignored\n")
    (root / "tracked.txt").write_text("should be tracked\n")

    new_repo, _stats = workspace.snapshot(settings)
    wc = new_repo.resolve_single(settings, "@")

    assert wc.file_exists("tracked.txt")
    assert not wc.file_exists("ignored.txt")
    assert wc.file_exists(".gitignore")  # the .gitignore file itself is tracked


def test_gitignore_in_subdirectory_only_affects_that_subtree(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "dir").mkdir()
    (root / "dir" / ".gitignore").write_text("*.log\n")
    (root / "dir" / "a.log").write_text("ignored\n")
    (root / "dir" / "a.txt").write_text("tracked\n")
    (root / "a.log").write_text("tracked (outside dir/)\n")

    new_repo, _stats = workspace.snapshot(settings)
    wc = new_repo.resolve_single(settings, "@")

    assert not wc.file_exists("dir/a.log")
    assert wc.file_exists("dir/a.txt")
    assert wc.file_exists("a.log")  # not under dir/, so dir/.gitignore doesn't apply


def test_previously_tracked_file_stays_tracked_even_if_later_gitignored(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("v1\n")
    workspace.snapshot(settings)

    (root / ".gitignore").write_text("a.txt\n")
    (root / "a.txt").write_text("v2\n")
    new_repo, _stats = workspace.snapshot(settings)
    wc = new_repo.resolve_single(settings, "@")

    # jj (like git) only consults .gitignore for *new* files, not to decide
    # whether to keep snapshotting an already-tracked one.
    assert wc.file_exists("a.txt")
    assert wc.read_file("a.txt") == b"v2\n"


def test_dotgit_is_always_ignored_even_without_a_gitignore_rule(workspace, repo, settings):
    """`.git` files/directories anywhere in the working copy are always
    skipped during snapshot, independent of any .gitignore -- mirrors
    lib/tests/test_local_working_copy.rs's test_dotgit_ignored (guards
    against accidentally snapshotting a nested repo's own git metadata).
    """
    root = Path(workspace.workspace_root)
    (root / "foo").mkdir()
    (root / "foo" / ".git").write_text("")
    (root / "foo" / "f").write_text("contents\n")

    new_repo, _stats = workspace.snapshot(settings)
    wc = new_repo.resolve_single(settings, "@")

    assert not wc.file_exists("foo/f")
    assert not wc.file_exists("foo/.git")
    assert wc.list_files() == []
