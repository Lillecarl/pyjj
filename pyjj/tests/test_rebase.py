"""Tests for Transaction.rebase(): jj rebase -r <rev> -d <dest> equivalent
for a single commit (descendants aren't moved along automatically -- same
convention as squash/split/set_executable: call rebase_descendants()
yourself afterward).
"""

from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def two_branches(repo, settings, wc_commit):
    """wc_commit is the root; build a `dest` commit and an independent
    `side` commit, both parented directly on wc_commit.
    """
    tx = repo.start_transaction(settings)
    b1 = tx.new_commit(settings, [wc_commit.id])
    b1.set_description("dest")
    dest = b1.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add dest")
    dest = repo.get_commit(dest.id)

    tx2 = repo.start_transaction(settings)
    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("side")
    side = b2.write(repo)
    tx2.rebase_descendants()
    repo = tx2.commit("add side")
    side = repo.get_commit(side.id)

    return repo, wc_commit, dest, side


def test_rebase_moves_commit_onto_new_parent(two_branches, settings):
    repo, _wc_commit, dest, side = two_branches

    tx = repo.start_transaction(settings)
    rebased = tx.rebase(side, [dest.id])
    tx.rebase_descendants()
    repo = tx.commit("rebase side onto dest")
    rebased = repo.get_commit(rebased.id)

    assert rebased.parent_ids == [dest.id]
    assert rebased.description == "side"


def test_rebase_preserves_content_not_just_metadata(repo, settings, workspace, wc_commit):
    Path(workspace.workspace_root, "dest.txt").write_text("dest content\n")
    repo, _ = workspace.snapshot(settings)
    dest = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [wc_commit.id])
    b.set_description("side")
    side = b.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add side")
    side = repo.get_commit(side.id)

    tx2 = repo.start_transaction(settings)
    rebased = tx2.rebase(side, [dest.id])
    tx2.rebase_descendants()
    repo = tx2.commit("rebase side onto dest")
    rebased = repo.get_commit(rebased.id)

    assert rebased.file_exists("dest.txt")  # inherited from new parent's tree


def test_rebase_descendants_follow_when_requested(two_branches, settings):
    repo, wc_commit, dest, side = two_branches

    # A child of `side`.
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [side.id])
    b.set_description("side child")
    child = b.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add side child")
    child = repo.get_commit(child.id)
    side = repo.get_commit(side.id)

    tx2 = repo.start_transaction(settings)
    tx2.rebase(side, [dest.id])
    tx2.rebase_descendants()
    repo = tx2.commit("rebase side (and its descendant) onto dest")

    new_child = repo.revset(settings, f"descendants({dest.id.hex()}) & description(glob:\"side child\")")
    assert len(new_child) == 1
    assert new_child[0].parent_ids != [side.id]  # side itself got a new id too
