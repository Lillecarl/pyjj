"""Tests for sparse checkout patterns: Workspace.sparse_patterns() /
.set_sparse_patterns() -- the `jj sparse list/set/reset` equivalents.
"""

from pathlib import Path

import pyjj


def _write(workspace, name, content):
    path = Path(workspace.workspace_root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_default_sparse_patterns_is_everything(workspace):
    assert workspace.sparse_patterns() == [""]


def test_narrowing_sparse_patterns_removes_unmatched_files_on_disk(workspace, settings):
    _write(workspace, "a.txt", "a\n")
    _write(workspace, "dir/b.txt", "b\n")
    workspace.snapshot(settings)

    root = Path(workspace.workspace_root)
    assert (root / "a.txt").exists()
    assert (root / "dir" / "b.txt").exists()

    stats = workspace.set_sparse_patterns(["dir"])
    assert workspace.sparse_patterns() == ["dir"]
    assert not (root / "a.txt").exists()
    assert (root / "dir" / "b.txt").exists()
    assert stats["removed_files"] >= 1


def test_widening_sparse_patterns_restores_files_on_disk(workspace, settings):
    _write(workspace, "a.txt", "a\n")
    _write(workspace, "dir/b.txt", "b\n")
    workspace.snapshot(settings)
    workspace.set_sparse_patterns(["dir"])

    root = Path(workspace.workspace_root)
    stats = workspace.set_sparse_patterns([""])
    assert workspace.sparse_patterns() == [""]
    assert (root / "a.txt").exists()
    assert (root / "dir" / "b.txt").exists()
    assert stats["added_files"] >= 1


def test_sparse_patterns_dont_affect_the_committed_tree(workspace, settings):
    _write(workspace, "a.txt", "a\n")
    _write(workspace, "dir/b.txt", "b\n")
    repo, _ = workspace.snapshot(settings)
    workspace.set_sparse_patterns(["dir"])

    wc = repo.resolve_single(settings, "@")
    assert wc.file_exists("a.txt")
    assert wc.file_exists("dir/b.txt")


def test_snapshot_ignores_changes_outside_the_sparse_patterns(workspace, settings):
    """Mirrors lib/tests/test_local_working_copy_sparse.rs's
    test_sparse_commit: narrowing the sparse patterns doesn't just remove
    files from disk (already covered above) -- snapshot() actively ignores
    any content that shows up outside the sparse view (e.g. recreated
    out-of-band), while still picking up real changes inside it.
    """
    _write(workspace, "file1", "contents")
    _write(workspace, "dir1/file1", "contents")
    workspace.snapshot(settings)

    workspace.set_sparse_patterns(["dir1"])

    root = Path(workspace.workspace_root)
    (root / "file1").write_text("modified-outside-sparse-view")
    (root / "dir1" / "file1").write_text("modified-inside-sparse-view")

    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    assert commit.read_file("file1") == b"contents"
    assert commit.read_file("dir1/file1") == b"modified-inside-sparse-view"


def test_sparse_pattern_changes_dont_create_a_new_operation(workspace, repo, settings):
    _write(workspace, "a.txt", "a\n")
    repo, _ = workspace.snapshot(settings)
    op_before = repo.operation.id

    workspace.set_sparse_patterns([])
    workspace.set_sparse_patterns([""])

    reloaded = workspace.load_at_head()
    assert reloaded.operation.id == op_before
