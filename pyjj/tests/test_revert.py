"""Tests for Transaction.revert_commit() -- the `jj revert` equivalent."""

from pathlib import Path

import pytest

import pyjj


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


def _advance(repo, settings, workspace, parent, description):
    """Creates a real child commit of `parent`, checks it out, and returns
    the (repo, commit) pair -- ready for the caller to write files and
    snapshot.
    """
    tx = repo.start_transaction(settings)
    seed = tx.new_commit(settings, [parent.id])
    seed.set_description(description)
    seed_commit = seed.write(repo)
    tx.set_wc_commit("default", seed_commit.id)
    tx.rebase_descendants()
    repo = tx.commit(f"advance to {description}")
    workspace.check_out(repo, seed_commit)
    return repo


@pytest.fixture
def commit_a_then_b(workspace, repo, settings):
    """commit A adds file.txt = 'hello\\n'; commit B (child of A) changes it
    to 'hello\\nworld\\n'.
    """
    root = repo.resolve_single(settings, "@")
    repo = _advance(repo, settings, workspace, root, "A")
    _write(workspace, "file.txt", "hello\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    repo = _advance(repo, settings, workspace, commit_a, "B")
    _write(workspace, "file.txt", "hello\nworld\n")
    repo, _ = workspace.snapshot(settings)
    commit_b = repo.resolve_single(settings, "@")

    return repo, commit_a, commit_b


def test_revert_commit_requires_at_least_one_parent(commit_a_then_b, settings):
    repo, _commit_a, commit_b = commit_a_then_b
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.revert_commit(commit_b, [])


def test_revert_onto_self_undoes_its_own_change(commit_a_then_b, settings, workspace):
    repo, _commit_a, commit_b = commit_a_then_b

    tx = repo.start_transaction(settings)
    builder = tx.revert_commit(commit_b, [commit_b.id])
    builder.set_description("revert append world")
    reverted = builder.write(repo)
    tx.set_wc_commit("default", reverted.id)
    tx.rebase_descendants()
    repo2 = tx.commit("revert append world")

    reverted = repo2.resolve_single(settings, str(reverted.change_id))
    assert not reverted.has_conflict
    assert reverted.read_file("file.txt") == b"hello\n"


def test_chained_revert_undoes_the_original_addition(commit_a_then_b, settings, workspace):
    """Reverting B onto itself, then reverting A onto that result, should
    leave file.txt entirely absent -- matching `jj revert -r B` followed by
    `jj revert -r A -d <result>`.
    """
    repo, commit_a, commit_b = commit_a_then_b

    tx = repo.start_transaction(settings)
    rb = tx.revert_commit(commit_b, [commit_b.id])
    rb.set_description("revert B")
    reverted_b = rb.write(repo)
    tx.set_wc_commit("default", reverted_b.id)
    tx.rebase_descendants()
    repo2 = tx.commit("revert B")
    reverted_b = repo2.resolve_single(settings, str(reverted_b.change_id))

    tx = repo2.start_transaction(settings)
    ra = tx.revert_commit(commit_a, [reverted_b.id])
    ra.set_description("revert A")
    reverted_a = ra.write(repo2)
    tx.set_wc_commit("default", reverted_a.id)
    tx.rebase_descendants()
    repo3 = tx.commit("revert A")

    reverted_a = repo3.resolve_single(settings, str(reverted_a.change_id))
    assert not reverted_a.file_exists("file.txt")


def test_revert_onto_divergent_destination_produces_a_conflict(
    commit_a_then_b, settings, workspace
):
    """Reverting B (which changed file.txt to 'hello\\nworld\\n') onto a
    sibling C that changed file.txt differently doesn't cleanly apply --
    real jj would show a conflict here too.
    """
    repo, commit_a, commit_b = commit_a_then_b

    repo = _advance(repo, settings, workspace, commit_a, "C")
    _write(workspace, "file.txt", "hello\nDIFFERENT\n")
    repo, _ = workspace.snapshot(settings)
    commit_c = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.revert_commit(commit_b, [commit_c.id])
    builder.set_description("revert B onto C")
    reverted = builder.write(repo)
    tx.set_wc_commit("default", reverted.id)
    tx.rebase_descendants()
    repo2 = tx.commit("revert B onto C")

    reverted = repo2.resolve_single(settings, str(reverted.change_id))
    assert reverted.has_conflict


def test_revert_commit_parent_is_the_given_new_parent(commit_a_then_b, settings):
    repo, commit_a, commit_b = commit_a_then_b
    tx = repo.start_transaction(settings)
    builder = tx.revert_commit(commit_b, [commit_a.id])
    builder.set_description("revert B onto A")
    reverted = builder.write(repo)
    assert reverted.parent_ids == [commit_a.id]
