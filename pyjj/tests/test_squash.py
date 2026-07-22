"""Tests for Transaction.squash(): jj squash equivalent."""

from pathlib import Path

import pytest

import pyjj


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


@pytest.fixture
def two_commit_chain(workspace, repo, settings):
    """commit_a (a.txt, b.txt) -> commit_b (b.txt modified, c.txt added),
    both built from real snapshots so trees reflect genuine file content.
    """
    _write(workspace, "a.txt", "a1\n")
    _write(workspace, "b.txt", "b1\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [commit_a.id])
    builder.set_description("commit b")
    commit_b_seed = builder.write(repo)
    tx.set_wc_commit("default", commit_b_seed.id)
    tx.rebase_descendants()
    repo = tx.commit("advance to commit b")
    workspace.check_out(repo, commit_b_seed)

    _write(workspace, "b.txt", "b2\n")
    _write(workspace, "c.txt", "c1\n")
    repo, _ = workspace.snapshot(settings)
    commit_b = repo.resolve_single(settings, "@")
    return repo, commit_a, commit_b


def test_squash_specific_path_moves_only_that_change(two_commit_chain, settings):
    repo, commit_a, commit_b = two_commit_chain
    tx = repo.start_transaction(settings)
    builder = tx.squash(commit_b, commit_a, paths=["b.txt"], keep_emptied=False)
    assert builder is not None
    builder.set_description("a (with b.txt squashed in)")
    new_a = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("squash b.txt")

    assert new_a.read_file("b.txt") == b"b2\n"
    assert new_a.file_exists("a.txt")
    assert not new_a.file_exists("c.txt")

    rewritten_b = repo2.resolve_single(settings, "@")
    assert rewritten_b.parent_ids == [new_a.id]
    diff = new_a.diff(rewritten_b)
    assert {e.path for e in diff} == {"c.txt"}


def test_squash_without_paths_takes_everything_and_abandons_source(two_commit_chain, settings):
    repo, commit_a, commit_b = two_commit_chain
    tx = repo.start_transaction(settings)
    builder = tx.squash(commit_b, commit_a, paths=None, keep_emptied=False)
    assert builder is not None
    builder.set_description("a (everything squashed)")
    new_a = builder.write(repo)
    tx.rebase_descendants()
    tx.set_wc_commit("default", new_a.id)
    repo2 = tx.commit("squash everything")

    assert repo2.resolve_single(settings, "@") == new_a
    assert new_a.file_exists("a.txt")
    assert new_a.file_exists("c.txt")
    assert new_a.read_file("b.txt") == b"b2\n"


def test_squash_with_no_matching_paths_returns_none(two_commit_chain, settings):
    repo, commit_a, commit_b = two_commit_chain
    tx = repo.start_transaction(settings)
    builder = tx.squash(commit_b, commit_a, paths=["no-such-file.txt"], keep_emptied=False)
    assert builder is None


def test_squash_keep_emptied_preserves_source(two_commit_chain, settings):
    repo, commit_a, commit_b = two_commit_chain
    tx = repo.start_transaction(settings)
    builder = tx.squash(commit_b, commit_a, paths=None, keep_emptied=True)
    assert builder is not None
    builder.set_description("a (everything squashed, source kept)")
    new_a = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("squash keep_emptied")

    # Source (rewritten to be empty relative to the new destination) should
    # still exist as a descendant, not be abandoned.
    descendants = repo2.revset(settings, f"children({new_a.id.hex()})")
    assert len(descendants) == 1
    empty_source = descendants[0]
    assert empty_source.is_empty(repo2)
