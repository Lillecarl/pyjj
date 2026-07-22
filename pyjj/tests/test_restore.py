"""Tests for Transaction.restore(): jj restore [paths] --from <src> --into
<dest> equivalent -- overwrite specific paths of one commit's tree with
another's content, with no ancestry relationship required between them
(unlike squash).
"""

from pathlib import Path

import pytest


def _advance(workspace, repo, settings, parent):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")
    workspace.check_out(repo, child)
    return repo


@pytest.fixture
def two_versions(workspace, repo, settings):
    """commit_v1 (a.txt="v1", b.txt="keep") -> commit_v2 (a.txt="v2",
    b.txt="changed"), both real snapshots.
    """
    Path(workspace.workspace_root, "a.txt").write_text("v1\n")
    Path(workspace.workspace_root, "b.txt").write_text("keep\n")
    repo, _ = workspace.snapshot(settings)
    commit_v1 = repo.resolve_single(settings, "@")

    repo = _advance(workspace, repo, settings, commit_v1)

    Path(workspace.workspace_root, "a.txt").write_text("v2\n")
    Path(workspace.workspace_root, "b.txt").write_text("changed\n")
    repo, _ = workspace.snapshot(settings)
    commit_v2 = repo.resolve_single(settings, "@")

    return repo, commit_v1, commit_v2


def test_restore_specific_path_only_touches_that_path(two_versions, settings):
    repo, commit_v1, commit_v2 = two_versions

    tx = repo.start_transaction(settings)
    builder = tx.restore(commit_v1, commit_v2, paths=["a.txt"])
    builder.set_description("restore a.txt")
    restored = builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("restore")

    assert restored.read_file("a.txt") == b"v1\n"
    assert restored.read_file("b.txt") == b"changed\n"  # untouched


def test_restore_without_paths_restores_everything(two_versions, settings):
    repo, commit_v1, commit_v2 = two_versions

    tx = repo.start_transaction(settings)
    builder = tx.restore(commit_v1, commit_v2)
    builder.set_description("restore everything")
    restored = builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("restore")

    assert restored.read_file("a.txt") == b"v1\n"
    assert restored.read_file("b.txt") == b"keep\n"


def test_restore_does_not_modify_the_source_commit(two_versions, settings):
    repo, commit_v1, commit_v2 = two_versions

    tx = repo.start_transaction(settings)
    builder = tx.restore(commit_v1, commit_v2, paths=["a.txt"])
    builder.set_description("restore a.txt")
    builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("restore")

    reloaded_v1 = repo.get_commit(commit_v1.id)
    assert reloaded_v1.read_file("a.txt") == b"v1\n"


def test_restore_works_across_unrelated_commits(repo, settings, wc_commit):
    """Unlike squash, `restore`'s `into_commit` need not be a descendant of
    `from_commit` at all.
    """
    tx = repo.start_transaction(settings)
    b1 = tx.new_commit(settings, [wc_commit.id])
    b1.set_description("branch a")
    branch_a = b1.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add branch a")
    branch_a = repo.get_commit(branch_a.id)

    tx2 = repo.start_transaction(settings)
    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("branch b")
    branch_b = b2.write(repo)
    tx2.rebase_descendants()
    repo = tx2.commit("add branch b")
    branch_b = repo.get_commit(branch_b.id)

    tx3 = repo.start_transaction(settings)
    builder = tx3.restore(branch_a, branch_b)
    builder.set_description("branch b restored from branch a")
    restored = builder.write(repo)
    tx3.rebase_descendants()
    tx3.commit("restore across branches")

    assert restored.parent_ids == branch_b.parent_ids
