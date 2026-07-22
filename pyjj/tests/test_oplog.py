"""Tests for the operation log: operation_log(), load_operation(), undo(),
redo(), and restore_operation() -- jj undo / jj redo / jj op restore
equivalents."""

import pytest

import pyjj


@pytest.fixture
def bookmark_history(repo, settings):
    """op0 (init) -> op1 (set 'mybookmark') -> op2 (delete 'mybookmark')."""
    op_after_init = repo.operation
    wc = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    tx.set_bookmark("mybookmark", wc.id)
    repo1 = tx.commit("set mybookmark")

    tx = repo1.start_transaction(settings)
    tx.delete_bookmark("mybookmark")
    repo2 = tx.commit("delete mybookmark")

    return repo2, op_after_init, wc


def test_operation_log_is_newest_first_and_complete(bookmark_history):
    repo2, op_after_init, _wc = bookmark_history
    log = repo2.operation_log()
    descriptions = [op.description for op in log]

    assert descriptions[0] == "delete mybookmark"
    assert "set mybookmark" in descriptions
    assert log[-1].id == op_after_init.id or descriptions[-1] == ""


def test_load_operation_by_id(bookmark_history):
    repo2, op_after_init, _wc = bookmark_history
    loaded = repo2.load_operation(op_after_init.id)
    assert loaded.id == op_after_init.id
    assert loaded == op_after_init


def test_load_operation_bad_id_raises(bookmark_history):
    repo2, _op_after_init, _wc = bookmark_history
    with pytest.raises(pyjj.JjError):
        repo2.load_operation("not-a-valid-op-id")


def test_undo_restores_deleted_bookmark(bookmark_history, settings):
    repo2, _op_after_init, wc = bookmark_history
    assert repo2.get_bookmark("mybookmark") is None

    tx = repo2.start_transaction(settings)
    undone_op, restored_to_op, description = tx.undo()
    repo3 = tx.commit(description)

    assert undone_op.description == "delete mybookmark"
    assert restored_to_op.description == "set mybookmark"
    assert description.startswith("undo: restore to operation ")
    bm = repo3.get_bookmark("mybookmark")
    assert bm is not None
    assert bm.target_ids[0] == wc.id


def test_redo_reapplies_the_undone_change(bookmark_history, settings):
    repo2, _op_after_init, _wc = bookmark_history
    tx = repo2.start_transaction(settings)
    _undone, _restored, undo_description = tx.undo()
    repo3 = tx.commit(undo_description)
    assert repo3.get_bookmark("mybookmark") is not None

    tx = repo3.start_transaction(settings)
    _undone2, _restored2, redo_description = tx.redo()
    repo4 = tx.commit(redo_description)

    assert redo_description.startswith("redo: restore to operation ")
    bm = repo4.get_bookmark("mybookmark")
    assert bm is None or not bm.target_ids


def test_redo_without_a_prior_undo_raises(bookmark_history, settings):
    repo2, _op_after_init, _wc = bookmark_history
    tx = repo2.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.redo()


def test_repeated_undo_walks_further_back_each_time(bookmark_history, settings):
    """Regression check for the undo-stack-jumping logic: two undo() calls
    in a row should land on two different (increasingly older) operations,
    not toggle between the same two states.
    """
    repo2, _op_after_init, _wc = bookmark_history

    tx = repo2.start_transaction(settings)
    _u1, restored1, desc1 = tx.undo()
    repo3 = tx.commit(desc1)

    tx = repo3.start_transaction(settings)
    _u2, restored2, desc2 = tx.undo()
    repo4 = tx.commit(desc2)

    assert restored1.id != restored2.id
    assert restored2.description in ("add workspace 'default'", "")


def test_restore_operation_to_arbitrary_past_op(bookmark_history, settings):
    repo2, op_after_init, _wc = bookmark_history
    tx = repo2.start_transaction(settings)
    tx.restore_operation(op_after_init)
    repo3 = tx.commit("manual restore to init")

    bm = repo3.get_bookmark("mybookmark")
    assert bm is None or not bm.target_ids


def test_restore_operation_what_repo_only_keeps_remote_tracking(bookmark_history, settings):
    """`what=["repo"]` restores local bookmarks/heads/wc but leaves
    remote-tracking state (and git refs) as the current transaction already
    has it.
    """
    repo2, op_after_init, _wc = bookmark_history
    tx = repo2.start_transaction(settings)
    tx.restore_operation(op_after_init, what=["repo"])
    repo3 = tx.commit("restore repo portion only")

    bm = repo3.get_bookmark("mybookmark")
    assert bm is None or not bm.target_ids


def test_restore_operation_unknown_what_entry_raises(bookmark_history, settings):
    repo2, op_after_init, _wc = bookmark_history
    tx = repo2.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.restore_operation(op_after_init, what=["bogus"])


def test_load_at_operation_shows_historical_view(bookmark_history, settings):
    repo2, op_after_init, _wc = bookmark_history

    repo_at_init = repo2.load_at_operation(op_after_init)
    assert repo_at_init.operation.id == op_after_init.id
    assert repo_at_init.get_bookmark("mybookmark") is None

    log = repo2.operation_log()
    set_op = next(op for op in log if op.description == "set mybookmark")
    repo_at_set = repo2.load_at_operation(set_op)
    bm = repo_at_set.get_bookmark("mybookmark")
    assert bm is not None

    # The historical load doesn't affect repo2 (the head) itself.
    assert repo2.get_bookmark("mybookmark") is None


def test_load_at_operation_accepts_a_reloaded_operation(bookmark_history):
    repo2, op_after_init, _wc = bookmark_history
    reloaded = repo2.load_operation(op_after_init.id)
    repo_at_reloaded = repo2.load_at_operation(reloaded)
    assert repo_at_reloaded.operation.id == op_after_init.id


def test_undo_at_the_genesis_operation_raises(bookmark_history, settings):
    """Regression test for a previously-undocumented gap: undo() should
    raise "cannot undo the root operation" when the repo is truly
    positioned at the genesis operation (0 parents, empty description) --
    not just the "add workspace 'default'" operation that comes right
    after it, which is what `repo.operation` was right after `init_*`
    before `load_at_operation()` existed to walk further back.
    """
    repo2, _op_after_init, _wc = bookmark_history
    genesis_op = repo2.operation_log()[-1]
    assert genesis_op.description == ""

    repo_at_genesis = repo2.load_at_operation(genesis_op)
    tx = repo_at_genesis.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.undo()
