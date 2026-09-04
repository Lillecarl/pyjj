"""Rewriting the root commit must raise, not abort the process.

The root commit has no parents, and jj_lib asserts on that rather than
returning an error -- `Store::write_commit`, `MutableRepo::
record_abandoned_commit`, `CommitBuilder::set_parents` and
`MutableRepo::new_parents` all do. An assertion inside a native
extension aborts the interpreter, so nothing Python can catch. `jj`
never reaches them because its CLI refuses immutable commits first, and
the root commit is immutable in every repository.

Each test names one path into those assertions.
"""

import pytest

import pyjj


@pytest.fixture
def root(repo, settings):
    return repo.resolve_single(settings, "root()")


def test_rewriting_it_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, root)
    builder.set_description("nope")
    with pytest.raises(pyjj.JjError, match="root commit"):
        builder.write(repo)


def test_abandoning_it_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.abandon_commit(root)


def test_abandoning_it_restoring_descendants_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.abandon_restoring_descendants([root.id])


def test_duplicating_it_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.duplicate([root])


def test_rebasing_it_raises(repo, settings, root, wc_commit):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.rebase(root, [wc_commit.id])


def test_splitting_it_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.split_selected(root, ["anything"])


def test_moving_it_raises(repo, settings, root, wc_commit):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.move_commits([root.id], [], [wc_commit.id], [])


def test_fixing_it_raises(repo, settings, root):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="root commit"):
        tx.fix_enumerate(settings, revset="root()")


def test_a_normal_commit_still_rewrites(repo, settings, wc_commit):
    """The guard must not catch anything else."""
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, wc_commit)
    builder.set_description("fine")
    assert builder.write(repo).description.strip() == "fine"
