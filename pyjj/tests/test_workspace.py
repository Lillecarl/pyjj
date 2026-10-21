"""Tests for Workspace.init_internal_git/init_colocated_git/load."""

import os

import pytest

import pyjj


def test_init_internal_git_creates_workspace(tmp_path, settings):
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(tmp_path))
    assert ws.workspace_root == str(tmp_path)
    assert os.path.isdir(ws.repo_path)
    assert not os.path.isdir(tmp_path / ".git")

    view = repo.view()
    assert "default" in view


def test_init_colocated_git_creates_git_dir(tmp_path, settings):
    ws, repo = pyjj.Workspace.init_colocated_git(settings, str(tmp_path))
    assert ws.workspace_root == str(tmp_path)
    assert os.path.isdir(tmp_path / ".git")
    assert "default" in repo.view()


def test_init_requires_existing_directory(tmp_path, settings):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(pyjj.WorkspaceInitError):
        pyjj.Workspace.init_internal_git(settings, str(missing))


def test_load_roundtrips_an_initialized_workspace(tmp_path, settings):
    pyjj.Workspace.init_internal_git(settings, str(tmp_path))

    loaded = pyjj.Workspace.load(settings, str(tmp_path))
    assert loaded.workspace_root == str(tmp_path)

    repo = loaded.load_at_head()
    assert "default" in repo.view()


def test_load_nonexistent_workspace_raises(tmp_path, settings):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(pyjj.WorkspaceLoadError):
        pyjj.Workspace.load(settings, str(empty))


def test_workspace_repr_contains_root(workspace):
    assert workspace.workspace_root in repr(workspace)


def test_add_workspace_records_the_new_workspace_on_its_operation(workspace, settings, tmp_path):
    _ws, repo = workspace.add_workspace(settings, str(tmp_path / "second"))
    assert repo.operation.workspace_name == "second"
