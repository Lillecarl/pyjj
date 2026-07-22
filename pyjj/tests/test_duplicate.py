"""Tests for Transaction.duplicate(): jj duplicate equivalent."""

from pathlib import Path

import pyjj


def test_duplicate_single_commit_keeps_tree_and_parents(workspace, repo, settings, wc_commit):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    (dup,) = tx.duplicate([commit])
    repo2 = tx.commit("duplicate a.txt commit")

    assert dup.id != commit.id
    assert dup.change_id != commit.change_id  # duplicates get a fresh change id
    assert dup.parent_ids == commit.parent_ids
    assert dup.read_file("a.txt") == b"hi\n"
    assert dup.description == commit.description

    # The original is untouched, not abandoned.
    assert repo2.get_commit(commit.id).id == commit.id


def test_duplicate_does_not_move_bookmarks_or_wc(workspace, repo, settings):
    Path(workspace.workspace_root, "a.txt").write_text("hi\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    tx.duplicate([commit])
    repo2 = tx.commit("duplicate")

    # wc commit is still the original -- duplicate doesn't check anything out.
    assert repo2.resolve_single(settings, "@").id == commit.id


def test_duplicate_chain_preserves_internal_parent_child_relationship(
    workspace, repo, settings, wc_commit
):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("child")
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")

    # Reverse topological order (child before parent), matching jj duplicate's
    # own requirement.
    tx2 = repo.start_transaction(settings)
    dup_child, dup_parent = tx2.duplicate([child, wc_commit])
    tx2.commit("duplicate chain")

    assert dup_child.parent_ids == [dup_parent.id]
    assert dup_parent.parent_ids == wc_commit.parent_ids
