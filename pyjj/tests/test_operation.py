"""Tests for ReadonlyRepo.operation and walking the operation log."""

import pyjj


def test_repo_has_an_operation(repo):
    op = repo.operation
    assert isinstance(op, pyjj.Operation)
    assert op.description == "add workspace 'default'"
    assert op.id
    # The `settings` fixture uses load_config=False for test hermeticity,
    # so hostname/username come back empty here — just check the type.
    assert isinstance(op.hostname, str)
    assert isinstance(op.username, str)


def test_operation_equality_and_repr(repo):
    op = repo.operation
    assert op == repo.operation
    assert op.id in repr(op)


def test_committing_a_transaction_creates_a_new_operation_with_parent(repo, settings):
    initial_op = repo.operation
    tx = repo.start_transaction(settings)
    new_repo = tx.commit("a new operation")

    new_op = new_repo.operation
    assert new_op != initial_op
    assert new_op.description == "a new operation"
    assert initial_op.id in new_op.parent_ids

    parents = new_op.parents()
    assert len(parents) == 1
    assert parents[0] == initial_op
