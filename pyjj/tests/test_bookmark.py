"""Tests for local bookmarks: read via ReadonlyRepo, mutate via Transaction."""

import pyjj


def test_no_bookmarks_initially(repo):
    assert repo.bookmarks() == []
    assert repo.get_bookmark("main") is None


def test_set_bookmark_visible_within_transaction(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_bookmark("main", wc_commit.id)

    bm = tx.get_bookmark("main")
    assert bm.name == "main"
    assert bm.target_ids == [wc_commit.id]
    assert not bm.has_conflict
    assert tx.bookmarks() == [bm]


def test_set_bookmark_visible_after_commit(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_bookmark("main", wc_commit.id)
    new_repo = tx.commit("add bookmark")

    bm = new_repo.get_bookmark("main")
    assert bm.name == "main"
    assert bm.target_ids == [wc_commit.id]
    assert new_repo.bookmarks() == [bm]


def test_delete_bookmark(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_bookmark("main", wc_commit.id)
    tx.delete_bookmark("main")

    assert tx.get_bookmark("main") is None
    assert tx.bookmarks() == []


def test_bookmark_repr(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_bookmark("main", wc_commit.id)
    bm = tx.get_bookmark("main")
    assert repr(bm) == "Bookmark(main, conflict=False)"


def test_rebase_descendants_moves_bookmark_to_the_rewritten_commit(repo, settings, wc_commit):
    """A bookmark pointing at a commit that gets rewritten should follow the
    rewrite once rebase_descendants() runs -- mirrors
    lib/tests/test_rewrite_transform.rs's
    test_rebase_descendants_basic_bookmark_update. No new binding needed:
    this is automatic MutableRepo::rebase_descendants() behavior.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("A")
    a = builder.write(repo)
    tx.set_bookmark("bm", a.id)
    tx.rebase_descendants()
    repo = tx.commit("setup")

    a = repo.get_commit(a.id)
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, a)
    builder.set_description("A - rewritten")
    a2 = builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("rewrite A")

    bm = repo.get_bookmark("bm")
    assert bm.target_ids == [a2.id]
    assert not bm.has_conflict


def test_rebase_descendants_moves_bookmark_to_abandoned_commits_parent(
    repo, settings, wc_commit
):
    """A bookmark pointing at an abandoned commit should move to that
    commit's parent -- mirrors
    test_rebase_descendants_update_bookmark_after_abandon.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("A")
    a = builder.write(repo)
    builder = tx.new_commit(settings, [a.id])
    builder.set_description("B")
    b = builder.write(repo)
    tx.set_bookmark("bm", b.id)
    tx.rebase_descendants()
    repo = tx.commit("setup")

    b = repo.get_commit(b.id)
    tx = repo.start_transaction(settings)
    tx.abandon_commit(b)
    tx.rebase_descendants()
    repo = tx.commit("abandon B")

    bm = repo.get_bookmark("bm")
    assert bm.target_ids == [a.id]
    assert not bm.has_conflict


def test_bookmark_moved_differently_by_concurrent_transactions_conflicts(
    workspace, repo, settings, wc_commit
):
    """Two transactions from the same base each move the same bookmark to a
    different target; reconciling the divergent operations at load time
    should leave the bookmark conflicted with both targets, not silently
    pick a winner -- mirrors jj_lib's own concurrent-bookmark-move tests in
    test_refs.rs/test_view.rs.
    """
    tx1 = repo.start_transaction(settings)
    b1 = tx1.new_commit(settings, [wc_commit.id])
    b1.set_description("from tx1")
    c1 = b1.write(repo)
    tx1.set_bookmark("mybookmark", c1.id)
    tx1.commit("tx1 op")

    tx2 = repo.start_transaction(settings)
    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("from tx2")
    c2 = b2.write(repo)
    tx2.set_bookmark("mybookmark", c2.id)
    tx2.commit("tx2 op")

    merged_repo = workspace.load_at_head()
    bm = merged_repo.get_bookmark("mybookmark")
    assert bm.has_conflict
    assert {t.hex() for t in bm.target_ids} == {c1.id.hex(), c2.id.hex()}

    # Force-setting resolves the conflict.
    tx3 = merged_repo.start_transaction(settings)
    tx3.set_bookmark("mybookmark", c1.id)
    resolved_repo = tx3.commit("resolve")
    resolved_bm = resolved_repo.get_bookmark("mybookmark")
    assert not resolved_bm.has_conflict
    assert resolved_bm.target_ids == [c1.id]
