"""Tests for Commit.diff_with_copies() -- copy/rename-aware diffing, as
opposed to plain Commit.diff() which never detects copies (a rename shows
up there as a "removed" + "added" pair).

Copy/rename detection is backend-dependent (content-similarity-based for
the git backend, via gix's tree-diff rewrite tracking) -- the `workspace`/
`repo` fixtures use `init_internal_git`, so it's exercised here.
"""

from pathlib import Path

LINES = "".join(f"line {i}\n" for i in range(50))


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


def test_plain_diff_does_not_detect_renames(workspace, repo, settings, wc_commit):
    _write(workspace, "a.txt", LINES)
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    Path(workspace.workspace_root, "a.txt").unlink()
    _write(workspace, "b.txt", LINES)
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    entries = commit1.diff(commit2)
    assert {e.status for e in entries} == {"removed", "added"}
    assert {e.path for e in entries} == {"a.txt", "b.txt"}
    assert all(e.source_path is None for e in entries)


def test_diff_with_copies_detects_a_rename(workspace, repo, settings, wc_commit):
    _write(workspace, "a.txt", LINES)
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    Path(workspace.workspace_root, "a.txt").unlink()
    _write(workspace, "b.txt", LINES)
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    entries = commit1.diff_with_copies(commit2)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.status == "renamed"
    assert entry.path == "b.txt"
    assert entry.source_path == "a.txt"


def test_diff_with_copies_detects_a_copy(workspace, repo, settings, wc_commit):
    _write(workspace, "a.txt", LINES)
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    # The git backend's copy detection only considers sources that are
    # *also* modified in the same diff -- so a.txt has to actually change
    # here for b.txt (introduced with a.txt's original content) to be
    # recognized as copied from it.
    _write(workspace, "b.txt", LINES)
    _write(workspace, "a.txt", LINES + "one more line\n")
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    entries = commit1.diff_with_copies(commit2)
    statuses = {e.status for e in entries}
    assert statuses == {"copied", "modified"}
    copied = next(e for e in entries if e.status == "copied")
    assert copied.path == "b.txt"
    assert copied.source_path == "a.txt"


def test_diff_with_copies_reports_unrelated_changes_normally(workspace, repo, settings, wc_commit):
    _write(workspace, "a.txt", "hello\n")
    repo, _ = workspace.snapshot(settings)
    commit1 = repo.resolve_single(settings, "@")

    _write(workspace, "unrelated.txt", "brand new, no similar content\n")
    repo, _ = workspace.snapshot(settings)
    commit2 = repo.resolve_single(settings, "@")

    entries = commit1.diff_with_copies(commit2)
    assert len(entries) == 1
    assert entries[0].status == "added"
    assert entries[0].path == "unrelated.txt"
    assert entries[0].source_path is None
