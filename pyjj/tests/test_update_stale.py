"""Tests for Workspace.update_stale() -- the `jj workspace update-stale`
equivalent.

Note: this binding implements a deliberately simpler subset of the real
`jj workspace update-stale` command. It detects staleness and resets the
working copy to the given fresh repo's recorded wc commit, but does *not*
attempt to snapshot and preserve any uncommitted edits still sitting in the
stale working copy first -- see the Rust doc comment on `update_stale` for
details.
"""

from pathlib import Path

import pytest

import pyjj


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


def test_update_stale_on_fresh_workspace_is_a_noop(workspace, settings):
    fresh = workspace.load_at_head()
    assert workspace.update_stale(fresh) is None


def test_update_stale_detects_and_recovers_stale_working_copy(workspace, settings, tmp_path):
    _write(workspace, "a.txt", "a\n")
    repo, _ = workspace.snapshot(settings)
    commit_a = repo.resolve_single(settings, "@")

    # Advance the repo's view (moving the wc commit to root()'s empty tree)
    # via a transaction that never touches the physical working copy or
    # calls workspace.check_out() -- this leaves the on-disk state pointing
    # at the old operation with a.txt still physically present, i.e.
    # genuinely stale relative to the new view.
    root_commit = repo.resolve_single(settings, "root()")
    tx = repo.start_transaction(settings)
    new_wc_builder = tx.new_commit(settings, [root_commit.id])
    new_wc_builder.set_description("advanced elsewhere")
    new_wc_commit = new_wc_builder.write(repo)
    tx.set_wc_commit("default", new_wc_commit.id)
    tx.rebase_descendants()
    repo2 = tx.commit("advance wc commit without checking out")

    assert (tmp_path / "a.txt").exists()

    fresh = workspace.load_at_head()
    assert fresh.operation.id == repo2.operation.id

    stats = workspace.update_stale(fresh)
    assert stats is not None
    assert stats["removed_files"] == 1
    assert stats["added_files"] == 0

    after = workspace.load_at_head()
    assert after.resolve_single(settings, "@").id == new_wc_commit.id
    assert not (tmp_path / "a.txt").exists()

    # Idempotent: calling again now reports "not stale".
    fresh2 = workspace.load_at_head()
    assert workspace.update_stale(fresh2) is None


def test_update_stale_requires_workspace_to_exist_in_repo_view(workspace, settings, tmp_path):
    second_dir = tmp_path / "second"
    second_ws, _second_repo = workspace.add_workspace(settings, str(second_dir))

    # Forget "second" from the view (from the "default" workspace), then
    # confirm update_stale on the now-orphaned second workspace raises
    # rather than panicking.
    repo_without_second = workspace.forget_workspaces(settings, ["second"])

    with pytest.raises(pyjj.JjError):
        second_ws.update_stale(repo_without_second)
