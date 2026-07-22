"""Tests for Workspace.op_abandon(): jj op abandon equivalent.

Unlike undo()/redo()/restore_operation() (Transaction methods that create a
*new* operation reverting/copying repo state), op_abandon() edits the
operation log itself -- pruning an operation (or contiguous range) and
reparenting descendant operations onto the range's root -- so it lives on
Workspace and takes no Transaction/commit() step.
"""

import pytest

import pyjj


def _describe(repo, settings, description):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [repo.resolve_single(settings, "@").id])
    builder.set_description(description)
    commit = builder.write(repo)
    tx.set_wc_commit("default", commit.id)
    tx.rebase_descendants()
    return tx.commit(description)


@pytest.fixture
def op_history(workspace, repo, settings):
    """init -> op1 ('first') -> op2 ('second') -> op3 ('third')."""
    repo = _describe(repo, settings, "first")
    repo = _describe(repo, settings, "second")
    repo = _describe(repo, settings, "third")
    return workspace, repo


def test_op_abandon_prunes_a_single_middle_operation(op_history):
    workspace, repo = op_history
    log = repo.operation_log()
    middle_op = next(op for op in log if op.description == "second")

    stats = workspace.op_abandon(middle_op.id)

    assert stats.changed
    assert stats.abandoned_count == 1
    assert stats.rewritten_count == 1


def test_op_abandon_removes_the_operation_from_the_log(op_history):
    workspace, repo = op_history
    log = repo.operation_log()
    middle_op = next(op for op in log if op.description == "second")

    workspace.op_abandon(middle_op.id)

    new_repo = workspace.load_at_head()
    descriptions = [op.description for op in new_repo.operation_log()]
    assert "second" not in descriptions
    assert "first" in descriptions
    assert "third" in descriptions


def test_op_abandon_current_head_raises(op_history):
    workspace, repo = op_history
    with pytest.raises(pyjj.JjError):
        workspace.op_abandon(repo.operation.id)


def test_op_abandon_root_operation_raises(op_history):
    workspace, repo = op_history
    root_op = repo.operation_log()[-1]
    with pytest.raises(pyjj.JjError):
        workspace.op_abandon(root_op.id)


def test_op_abandon_range_syntax_prunes_the_operation_and_its_ancestors(op_history):
    """`..<op>` abandons `<op>` and everything back to the root, reparenting
    `<op>`'s descendants onto the root -- matching the CLI's own doc comment
    on `jj op abandon`."""
    workspace, repo = op_history
    log = repo.operation_log()
    first_op = next(op for op in log if op.description == "first")

    stats = workspace.op_abandon(f"..{first_op.id}")

    assert stats.changed
    new_repo = workspace.load_at_head()
    descriptions = [op.description for op in new_repo.operation_log()]
    assert "first" not in descriptions
    assert "second" in descriptions
    assert "third" in descriptions


def test_op_abandon_is_a_no_op_when_range_is_a_single_point(op_history):
    workspace, repo = op_history
    log = repo.operation_log()
    first_op = next(op for op in log if op.description == "first")

    stats = workspace.op_abandon(f"{first_op.id}..{first_op.id}")

    assert not stats.changed
    assert stats.abandoned_count == 0
