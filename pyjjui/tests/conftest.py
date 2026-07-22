"""Shared fixtures for the pyjjui test suite. Repo-construction logic lives
in testutils.py (shared with pyjjui/tools/screenshot.py); fixtures here are
thin pytest wrappers around it.
"""

from pathlib import Path

import pytest

import pyjj
from pyjjui.app import PyjjuiApp

from . import testutils

_DEV_SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / ".dev" / "screenshots"


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


@pytest.fixture
def render(request):
    """`render(app, "label")` dumps a PNG of a running app's current screen
    into `pyjjui/.dev/screenshots/` (gitignored), named after the calling
    test so renders from a `pytest` run of interaction tests double as visual
    feedback while developing -- no separate script invocation, no
    interactive terminal. Purely a side-channel for a human/Claude to look
    at; never asserted against (that's what snapshot tests and the assertions
    already in the test body are for). Call it anywhere inside `async with
    app.run_test() as pilot:` -- `export_screenshot()` requires the app to
    actually be running.
    """
    calls = {"n": 0}

    def _render(app: PyjjuiApp, label: str = "") -> Path:
        import cairosvg

        calls["n"] += 1
        _DEV_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        suffix = f"-{label}" if label else ""
        out = _DEV_SCREENSHOTS_DIR / f"{request.node.name}-{calls['n']}{suffix}.png"
        svg = app.export_screenshot()
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out))
        return out

    return _render
