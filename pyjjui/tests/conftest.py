"""Shared fixtures for the pyjjui test suite. Repo-construction logic lives
in testutils.py (shared with pyjjui/tools/screenshot.py); fixtures here are
thin pytest wrappers around it.
"""

import pytest

import pyjj
from pyjjui.app import PyjjuiApp

from . import testutils


@pytest.fixture
def settings(tmp_path_factory, monkeypatch):
    """Deterministic settings, isolated from whatever real jj config exists
    on the machine running the tests. Lives in its own directory, never the
    workspace root a given test's `tmp_path` points at, so it never shows up
    as a stray file in a test's working copy.
    """
    config_dir = tmp_path_factory.mktemp("jj_config")
    config_file = config_dir / "config.toml"
    testutils.write_config(config_file)
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    return pyjj.UserSettings()


@pytest.fixture
def workspace_and_repo(tmp_path, settings):
    return pyjj.Workspace.init_internal_git(settings, str(tmp_path))


@pytest.fixture
def workspace(workspace_and_repo):
    ws, _repo = workspace_and_repo
    return ws


@pytest.fixture
def seeded_repo(workspace, settings):
    return testutils.seed_repo(workspace, settings)


@pytest.fixture
def app(workspace, settings, seeded_repo):
    return PyjjuiApp(workspace=workspace, settings=settings, revset="all()")
