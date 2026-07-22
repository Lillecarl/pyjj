"""Tests for multi-workspace support: Workspace.add_workspace(),
.forget_workspaces(), .rename_workspace(), and .workspace_path() -- the
`jj workspace add/forget/rename/list` equivalents.
"""

from pathlib import Path

import pytest

import pyjj


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


def test_default_workspace_name(workspace):
    assert workspace.workspace_name == "default"


def test_add_workspace_creates_independent_working_copy(workspace, repo, settings, tmp_path):
    _write(workspace, "shared.txt", "shared\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    second_dir = tmp_path / "second"
    second_ws, second_repo = workspace.add_workspace(settings, str(second_dir))

    assert second_ws.workspace_name == "second"
    assert second_ws.workspace_root == str(second_dir)

    view = second_repo.view()
    assert set(view) == {"default", "second"}

    second_wc = second_repo.get_commit(pyjj.CommitId(view["second"]))
    # No revisions given -> parents of the current (default) workspace's own
    # wc commit's parents, i.e. base's own parents (not base itself).
    assert second_wc.parent_ids == base.parent_ids


def test_add_workspace_with_explicit_name_and_revisions(workspace, repo, settings, tmp_path):
    _write(workspace, "a.txt", "a\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    dest = tmp_path / "third"
    third_ws, third_repo = workspace.add_workspace(
        settings, str(dest), name="custom-name", revision_ids=[base.id]
    )

    assert third_ws.workspace_name == "custom-name"
    view = third_repo.view()
    third_wc = third_repo.get_commit(pyjj.CommitId(view["custom-name"]))
    assert third_wc.parent_ids == [base.id]


def test_add_workspace_duplicate_name_raises(workspace, settings, tmp_path):
    workspace.add_workspace(settings, str(tmp_path / "second"))
    with pytest.raises(pyjj.JjError):
        workspace.add_workspace(settings, str(tmp_path / "dup"), name="second")


def test_workspace_path_reports_recorded_location(workspace, settings, tmp_path):
    dest = tmp_path / "second"
    workspace.add_workspace(settings, str(dest))
    assert workspace.workspace_path("second") is not None
    assert workspace.workspace_path("does-not-exist") is None


def test_forget_workspaces_removes_from_view_only(workspace, settings, tmp_path):
    second_dir = tmp_path / "second"
    workspace.add_workspace(settings, str(second_dir))

    repo_after = workspace.forget_workspaces(settings, ["second"])
    view = repo_after.view()
    assert "second" not in view
    assert "default" in view
    # Forgetting doesn't touch anything on disk.
    assert second_dir.exists()


def test_forget_workspaces_empty_list_raises(workspace, settings):
    with pytest.raises(pyjj.JjError):
        workspace.forget_workspaces(settings, [])


def test_forget_workspaces_unknown_name_raises(workspace, settings):
    with pytest.raises(pyjj.JjError):
        workspace.forget_workspaces(settings, ["not-a-real-workspace"])


def test_rename_workspace_updates_view_and_name(workspace, settings):
    repo_after = workspace.rename_workspace(settings, "renamed")
    assert workspace.workspace_name == "renamed"
    view = repo_after.view()
    assert "renamed" in view
    assert "default" not in view


def test_rename_workspace_to_same_name_is_a_noop(workspace, settings, repo):
    before = repo.view()
    after = workspace.rename_workspace(settings, "default")
    assert after.view() == before
    assert workspace.workspace_name == "default"


def test_workspace_still_functions_after_rename(workspace, settings):
    workspace.rename_workspace(settings, "renamed")
    _write(workspace, "after-rename.txt", "still works\n")
    repo, _ = workspace.snapshot(settings)
    wc = repo.resolve_single(settings, "@")
    assert wc.read_file("after-rename.txt") == b"still works\n"
