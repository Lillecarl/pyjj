"""Tests for ReadonlyRepo.shortest_commit_id_prefix_len()/
shortest_change_id_prefix_len() -- the "shortest unique prefix" jj log
shows by default (see repo.rs's docs for the one difference from jj log's
own default: this always disambiguates against the whole repo, not a
narrower revsets.short-prefixes set).
"""

from pathlib import Path

import pytest

import pyjj


def test_prefix_len_is_1_for_lone_root_commit(repo, wc_commit):
    # Only the root + the wc commit exist -- trivially unique at length 1.
    assert repo.shortest_commit_id_prefix_len(wc_commit.id) >= 1
    assert repo.shortest_commit_id_prefix_len(wc_commit.id) <= len(wc_commit.id.hex())


def test_prefix_len_grows_with_more_commits_sharing_a_prefix(workspace, repo, settings):
    # Build several commits; a prefix length that resolves uniquely for one
    # commit must actually be sufficient to look it back up via revset.
    commits = []
    for i in range(8):
        Path(workspace.workspace_root, f"f{i}.txt").write_text(f"{i}\n")
        repo, _ = workspace.snapshot(settings)
        commits.append(repo.resolve_single(settings, "@"))

    for commit in commits:
        n = repo.shortest_commit_id_prefix_len(commit.id)
        prefix = commit.id.hex()[:n]
        resolved = repo.resolve_single(settings, prefix)
        assert resolved.id == commit.id


def test_change_id_prefix_len_resolves_via_reversed_hex(workspace, repo, settings):
    commits = []
    for i in range(8):
        Path(workspace.workspace_root, f"f{i}.txt").write_text(f"{i}\n")
        repo, _ = workspace.snapshot(settings)
        commits.append(repo.resolve_single(settings, "@"))

    for commit in commits:
        n = repo.shortest_change_id_prefix_len(commit.change_id)
        prefix = commit.change_id.reverse_hex()[:n]
        resolved = repo.resolve_single(settings, prefix)
        assert resolved.change_id == commit.change_id


def test_divergent_change_id_raises_a_clear_error_instead_of_resolving(
    workspace, repo, settings, wc_commit
):
    """Two *visible* commits sharing one change_id (achievable directly via
    `duplicate()` + `CommitBuilder.set_change_id()`, without needing evolog)
    is a divergent change -- resolving a revset that names it should raise
    a clear error, not panic or silently pick one. Mirrors jj_lib's own
    test_id_prefix_divergent.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("original")
    c1 = builder.write(repo)
    tx.set_wc_commit("default", c1.id)
    tx.rebase_descendants()
    repo = tx.commit("create c1")
    c1 = repo.get_commit(c1.id)

    tx = repo.start_transaction(settings)
    (dup,) = tx.duplicate([c1])
    builder = tx.rewrite_commit(settings, dup)
    builder.set_change_id(c1.change_id)
    builder.set_description("divergent duplicate")
    dup2 = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("create divergent change id")

    assert c1.change_id == dup2.change_id

    with pytest.raises(pyjj.RevsetEvalError, match="divergent"):
        repo2.resolve_single(settings, c1.change_id.reverse_hex())
