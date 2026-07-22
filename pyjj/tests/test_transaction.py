"""Tests for Transaction: new_commit, rewrite_commit, commit lifecycle."""

import pytest

import pyjj


def test_new_commit_requires_at_least_one_parent(repo, settings):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.TransactionError):
        tx.new_commit(settings, [])


def test_new_commit_creates_commit_with_given_parent(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("a new commit")
    new = builder.write(repo)
    assert new.parent_ids == [wc_commit.id]
    assert new.description == "a new commit"


def test_rewrite_commit_keeps_change_id_but_changes_commit_id(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, wc_commit)
    builder.set_description("rewritten")
    rewritten = builder.write(repo)

    assert rewritten.change_id == wc_commit.change_id
    assert rewritten.id != wc_commit.id
    assert rewritten.description == "rewritten"


def test_full_describe_workflow_updates_view_after_commit(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, wc_commit)
    builder.set_description("describe workflow")
    rewritten = builder.write(repo)

    tx.set_wc_commit("default", rewritten.id)
    tx.rebase_descendants()
    new_repo = tx.commit("describe: describe workflow")

    assert new_repo.view()["default"] == rewritten.id.hex()


def test_rebase_descendants_returns_count(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, wc_commit)
    builder.set_description("x")
    rewritten = builder.write(repo)
    tx.set_wc_commit("default", rewritten.id)

    count = tx.rebase_descendants()
    assert isinstance(count, int)
    assert count == 0  # no descendants of the working-copy commit


def test_editing_an_existing_ancestor_rebases_its_descendants(repo, settings, wc_commit):
    """`jj edit <rev>` equivalent: point the wc at an *existing* commit
    (not a new child), rewrite it in place, and confirm its descendants --
    not just the wc pointer -- follow onto the rewritten version.
    """
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

    # "jj edit c1" -- re-point wc at c1 directly, no new commit created.
    tx3 = repo.start_transaction(settings)
    tx3.set_wc_commit("default", c1.id)
    tx3.rebase_descendants()
    repo = tx3.commit("edit c1")
    assert repo.view()["default"] == c1.id.hex()

    # Now edit c1's content in place; c2 should get rebased onto the result.
    tx4 = repo.start_transaction(settings)
    builder = tx4.rewrite_commit(settings, c1)
    builder.set_description("c1 edited")
    new_c1 = builder.write(repo)
    tx4.set_wc_commit("default", new_c1.id)
    count = tx4.rebase_descendants()
    repo = tx4.commit("describe c1")

    assert count == 1
    new_c2 = repo.revset(settings, f"children({new_c1.id.hex()})")
    assert len(new_c2) == 1
    assert new_c2[0].description == "c2"
    assert new_c2[0].id != c2.id


def test_commit_twice_raises_transaction_error(repo, settings):
    tx = repo.start_transaction(settings)
    tx.commit("first")
    with pytest.raises(pyjj.TransactionError):
        tx.commit("second")


def test_operating_on_committed_transaction_raises(repo, settings):
    tx = repo.start_transaction(settings)
    tx.commit("done")
    with pytest.raises(pyjj.TransactionError):
        tx.new_commit(settings, [])
    with pytest.raises(pyjj.TransactionError):
        tx.rebase_descendants()


def test_transaction_repr_reflects_open_and_consumed_state(repo, settings):
    tx = repo.start_transaction(settings)
    assert repr(tx) == "Transaction(open)"
    tx.commit("done")
    assert repr(tx) == "Transaction(consumed)"
