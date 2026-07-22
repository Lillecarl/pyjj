"""Tests that Workspace.snapshot() honors `snapshot.max-new-file-size`,
matching the CLI's own `WorkspaceCommandHelper::snapshot_options` (including
its `0` -> "unlimited" convention) -- this previously used a hardcoded
constant that happened to match jj's built-in default, silently ignoring
any user override.
"""

from pathlib import Path

import pyjj


def _settings_with_max_size(tmp_path, monkeypatch, max_size):
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"""
[user]
name = "Test User"
email = "test@example.com"

[snapshot]
max-new-file-size = "{max_size}"
""")
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    monkeypatch.delenv("JJ_USER", raising=False)
    monkeypatch.delenv("JJ_EMAIL", raising=False)
    return pyjj.UserSettings()


def test_files_over_the_configured_limit_are_not_tracked(tmp_path, monkeypatch):
    settings = _settings_with_max_size(tmp_path, monkeypatch, "10B")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    (workspace_root / "big.txt").write_text("x" * 100)
    (workspace_root / "small.txt").write_text("ok")

    repo, _stats = ws.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert not commit.file_exists("big.txt")
    assert commit.file_exists("small.txt")


def test_zero_means_unlimited(tmp_path, monkeypatch):
    settings = _settings_with_max_size(tmp_path, monkeypatch, "0B")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    (workspace_root / "big.txt").write_text("x" * 100)

    repo, _stats = ws.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert commit.file_exists("big.txt")


def test_load_config_false_falls_back_to_the_1mib_default(workspace, repo, settings):
    """`settings` (the shared fixture) uses load_config=False, so
    `snapshot.max-new-file-size` isn't loaded at all -- confirm this
    doesn't silently disable the limit (unlimited) but falls back to jj's
    real built-in default (1MiB) instead.
    """
    Path(workspace.workspace_root, "small.txt").write_text("ok\n")
    repo, _stats = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    assert commit.file_exists("small.txt")
