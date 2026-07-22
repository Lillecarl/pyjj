"""Shared fixtures for the pyjj test suite.

Every fixture that creates a workspace hands back a fresh directory per
test (via pytest's `tmp_path`), since jj workspaces need an existing,
empty directory to initialize into.
"""

import pytest

import pyjj


@pytest.fixture
def settings():
    """Deterministic settings, ignoring whatever real jj config happens to
    exist on the machine running the tests -- `UserSettings()` loads real
    config by default (see AGENTS.md), so tests that want hermeticity must
    opt out explicitly.
    """
    return pyjj.UserSettings(load_config=False)


@pytest.fixture
def workspace_and_repo(tmp_path, settings):
    """A freshly-initialized internal-git workspace and its repo."""
    return pyjj.Workspace.init_internal_git(settings, str(tmp_path))


@pytest.fixture
def workspace(workspace_and_repo):
    ws, _repo = workspace_and_repo
    return ws


@pytest.fixture
def repo(workspace_and_repo):
    _ws, repo = workspace_and_repo
    return repo


@pytest.fixture
def wc_commit(repo):
    """The initial (empty) working-copy commit."""
    view = repo.view()
    wc_hex = next(iter(view.values()))
    return repo.get_commit(pyjj.CommitId(wc_hex))
