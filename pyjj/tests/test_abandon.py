"""Tests for Transaction.abandon_commit(): jj abandon <rev> equivalent."""

import pytest

import pyjj


@pytest.fixture
def commit_chain(repo, settings, wc_commit):
    """root -> c1 -> c2, c2 is the wc commit."""
    tx = repo.start_transaction(settings)
    b1 = tx.new_commit(settings, [wc_commit.id])
    b1.set_description("c1")
    c1 = b1.write(repo)
    tx.set_wc_commit("default", c1.id)
    tx.rebase_descendants()
    repo = tx.commit("add c1")
    c1 = repo.get_commit(c1.id)

    tx2 = repo.start_transaction(settings)
    b2 = tx2.new_commit(settings, [c1.id])
    b2.set_description("c2")
    c2 = b2.write(repo)
    tx2.set_wc_commit("default", c2.id)
    tx2.rebase_descendants()
    repo = tx2.commit("add c2")
    c2 = repo.get_commit(c2.id)

    return repo, wc_commit, c1, c2


def test_abandoning_middle_commit_rebases_descendants_onto_its_parents(commit_chain, settings):
    repo, root_wc, c1, _c2 = commit_chain

    tx = repo.start_transaction(settings)
    tx.abandon_commit(c1)
    tx.rebase_descendants()
    repo = tx.commit("abandon c1")

    new_wc = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    assert new_wc.parent_ids == [root_wc.id]


def test_abandoning_the_wc_commit_gives_a_fresh_child_of_its_parent(commit_chain, settings):
    repo, root_wc, c1, c2 = commit_chain

    tx = repo.start_transaction(settings)
    tx.abandon_commit(c2)
    tx.rebase_descendants()
    repo = tx.commit("abandon c2 (the wc commit)")

    new_wc = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    assert new_wc.id != c2.id
    assert new_wc.parent_ids == [c1.id]
    assert new_wc.parent_ids != [root_wc.id]


def test_abandoned_commit_is_no_longer_an_ancestor_of_the_wc(commit_chain, settings):
    """The abandoned commit's data still exists (resolvable by direct id,
    same as real jj's "hidden but not deleted" commits), but it's dropped
    out of the visible history reachable from the new wc commit.
    """
    repo, _root_wc, c1, _c2 = commit_chain

    tx = repo.start_transaction(settings)
    tx.abandon_commit(c1)
    tx.rebase_descendants()
    repo = tx.commit("abandon c1")

    assert repo.revset(settings, f"{c1.id.hex()} & ::@") == []
