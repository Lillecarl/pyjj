"""Tests for Transaction.move_commits(): the unified `jj rebase` primitive
covering every destination mode (-d/-A/-B) and both source modes (-r's
specific commits vs -s's root-plus-descendants), via
`jj_lib::rewrite::move_commits`. Unlike `Transaction.rebase()` (a single
commit, descendants untouched), this one moves whole target sets and can
splice into the middle of the graph.
"""

import pytest

import pyjj


@pytest.fixture
def two_branches(repo, settings, wc_commit):
    """wc_commit is the root; `dest` and `side` are both direct children of
    it, on independent branches -- same shape `test_rebase.py` uses.
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


def test_move_commits_onto_rebases_the_target_commit(two_branches, settings):
    repo, _wc_commit, dest, side = two_branches

    tx = repo.start_transaction(settings)
    stats = tx.move_commits([side.id], [], [dest.id], [])
    tx.rebase_descendants()
    repo = tx.commit("rebase side onto dest")

    rebased = repo.revset(settings, 'description(exact:"side")')[0]
    assert rebased.parent_ids == [dest.id]
    assert stats.num_rebased_targets == 1


def test_move_commits_with_root_target_pulls_descendants_along(two_branches, settings):
    repo, _wc_commit, dest, side = two_branches

    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [side.id])
    b.set_description("side child")
    child = b.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add side child")
    side = repo.get_commit(side.id)

    tx2 = repo.start_transaction(settings)
    stats = tx2.move_commits([], [side.id], [dest.id], [])
    tx2.rebase_descendants()
    repo = tx2.commit("rebase side and its descendant onto dest")

    rebased_side = repo.revset(settings, 'description(exact:"side")')[0]
    rebased_child = repo.revset(settings, 'description(exact:"side child")')[0]
    assert rebased_side.parent_ids == [dest.id]
    assert rebased_child.parent_ids == [rebased_side.id]
    # `Roots` target counts the whole expanded set (root + descendants) as
    # "targets", not "descendants" -- unlike the `Commits` target case above.
    assert stats.num_rebased_targets == 2


def test_move_commits_insert_after_splices_in_as_a_new_child(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    b1 = tx.new_commit(settings, [wc_commit.id])
    b1.set_description("original child")
    original_child = b1.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("add original child")
    original_child = repo.get_commit(original_child.id)

    tx2 = repo.start_transaction(settings)
    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("inserted")
    inserted = b2.write(repo)
    tx2.rebase_descendants()
    repo = tx2.commit("add inserted, parallel to original child")
    inserted = repo.get_commit(inserted.id)

    # Insert `inserted` right after wc_commit: it becomes wc_commit's child,
    # and original_child (wc_commit's existing child) becomes inserted's
    # child instead -- same as `jj rebase -r inserted -A wc_commit`.
    tx3 = repo.start_transaction(settings)
    stats = tx3.move_commits([inserted.id], [], [wc_commit.id], [original_child.id])
    tx3.rebase_descendants()
    repo = tx3.commit("insert after wc_commit")

    rebased_inserted = repo.revset(settings, 'description(exact:"inserted")')[0]
    rebased_original = repo.revset(settings, 'description(exact:"original child")')[0]
    assert rebased_inserted.parent_ids == [wc_commit.id]
    assert rebased_original.parent_ids == [rebased_inserted.id]
    # `inserted`'s own parent list doesn't change (still wc_commit) -- only
    # `original child`'s does, so it's counted as a rebased descendant, and
    # `inserted` itself as "skipped" (already in place).
    assert stats.num_rebased_descendants == 1
    assert stats.num_skipped_rebases == 1


def test_move_commits_insert_before_splices_in_as_a_new_parent(two_branches, settings):
    repo, wc_commit, dest, side = two_branches

    # Insert `side` right before `dest`: side takes over dest's original
    # parents, dest becomes side's child -- same as
    # `jj rebase -r side -B dest`.
    tx = repo.start_transaction(settings)
    stats = tx.move_commits([side.id], [], dest.parent_ids, [dest.id])
    tx.rebase_descendants()
    repo = tx.commit("insert before dest")

    rebased_side = repo.revset(settings, 'description(exact:"side")')[0]
    rebased_dest = repo.revset(settings, 'description(exact:"dest")')[0]
    assert rebased_side.parent_ids == [wc_commit.id]
    assert rebased_dest.parent_ids == [rebased_side.id]
    # side's own parent list is unchanged (still wc_commit) -- only dest's
    # is, so dest is the rebased descendant and side counts as "skipped".
    assert stats.num_rebased_descendants == 1
    assert stats.num_skipped_rebases == 1


def test_move_commits_requires_exactly_one_target_kind(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.move_commits([], [], [wc_commit.id], [])
    with pytest.raises(pyjj.JjError):
        tx.move_commits([wc_commit.id], [wc_commit.id], [wc_commit.id], [])
