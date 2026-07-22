"""Tests for Commit.annotate(): jj file annotate <path> equivalent (blame)."""

from pathlib import Path

import pyjj


def _new_child(repo, settings, workspace, parent):
    """Advance the workspace's wc commit to a fresh child of `parent`, so
    a subsequent snapshot() amends *that* commit rather than `parent`
    itself -- giving real parent/child ancestry to blame across.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("new child")
    workspace.check_out(repo, child)
    return repo


def test_annotate_attributes_each_line_to_the_commit_that_added_it(workspace, repo, settings):
    Path(workspace.workspace_root, "f.txt").write_text("line1\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    repo = _new_child(repo, settings, workspace, commit_a)

    Path(workspace.workspace_root, "f.txt").write_text("line1\nline2\n")
    repo, _ = workspace.snapshot(settings)
    commit_b = repo.resolve_single(settings, "@")

    lines = commit_b.annotate(repo, "f.txt")
    assert [(l.commit_id, l.line) for l in lines] == [
        (commit_a.id, b"line1\n"),
        (commit_b.id, b"line2\n"),
    ]
    assert all(not l.is_boundary for l in lines)


def test_annotate_reflects_line_modification(workspace, repo, settings):
    Path(workspace.workspace_root, "f.txt").write_text("line1\nline2\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    repo = _new_child(repo, settings, workspace, commit_a)

    Path(workspace.workspace_root, "f.txt").write_text("line1 changed\nline2\n")
    repo, _ = workspace.snapshot(settings)
    commit_b = repo.resolve_single(settings, "@")

    lines = commit_b.annotate(repo, "f.txt")
    assert [(l.commit_id, l.line) for l in lines] == [
        (commit_b.id, b"line1 changed\n"),
        (commit_a.id, b"line2\n"),
    ]


def test_annotate_on_file_never_modified_attributes_all_to_originating_commit(
    workspace, repo, settings
):
    Path(workspace.workspace_root, "f.txt").write_text("a\nb\nc\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    lines = commit_a.annotate(repo, "f.txt")
    assert all(l.commit_id == commit_a.id for l in lines)
    assert [l.line for l in lines] == [b"a\n", b"b\n", b"c\n"]
