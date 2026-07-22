"""Tests for `working-copy.eol-conversion`, mirroring lib/tests/test_eol.rs.

This is entirely config-driven (`TreeStateSettings::try_from_user_settings`
reads it from the `UserSettings` passed to `Workspace.init_*`/`.load()`), so
no new pyjj binding was needed -- just coverage confirming the existing
snapshot()/check_out() bindings honor it correctly, same as the CLI does.
"""

import pytest

import pyjj

LF_CONTENT = b"aaa\nbbbb\nccccc\n"
CRLF_CONTENT = b"aaa\r\nbbbb\r\nccccc\r\n"
MIXED_CONTENT = b"aaa\nbbbb\r\nccccc\n"
BINARY_CONTENT = b"\0"


def _workspace_with_eol_mode(tmp_path, monkeypatch, mode):
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"""
[user]
name = "Test User"
email = "test@example.com"

[working-copy]
eol-conversion = "{mode}"
""")
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    monkeypatch.delenv("JJ_USER", raising=False)
    monkeypatch.delenv("JJ_EMAIL", raising=False)
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))
    return ws, repo, settings, workspace_root


@pytest.mark.parametrize(
    "mode,file_content,expected_stored",
    [
        ("input-output", LF_CONTENT, LF_CONTENT),
        ("input-output", CRLF_CONTENT, LF_CONTENT),
        ("input-output", MIXED_CONTENT, LF_CONTENT),
        ("input-output", BINARY_CONTENT, BINARY_CONTENT),
        ("input", LF_CONTENT, LF_CONTENT),
        ("input", CRLF_CONTENT, LF_CONTENT),
        ("input", MIXED_CONTENT, LF_CONTENT),
        ("input", BINARY_CONTENT, BINARY_CONTENT),
        ("none", LF_CONTENT, LF_CONTENT),
        ("none", CRLF_CONTENT, CRLF_CONTENT),
        ("none", MIXED_CONTENT, MIXED_CONTENT),
        ("none", BINARY_CONTENT, BINARY_CONTENT),
    ],
)
def test_eol_conversion_on_snapshot(tmp_path, monkeypatch, mode, file_content, expected_stored):
    ws, repo, settings, workspace_root = _workspace_with_eol_mode(tmp_path, monkeypatch, mode)
    (workspace_root / "f.txt").write_bytes(file_content)

    repo, _stats = ws.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    assert commit.read_file("f.txt") == expected_stored


def test_input_output_mode_restores_crlf_on_checkout(tmp_path, monkeypatch):
    ws, repo, settings, workspace_root = _workspace_with_eol_mode(
        tmp_path, monkeypatch, "input-output"
    )
    path = workspace_root / "f.txt"
    path.write_bytes(CRLF_CONTENT)
    repo, _stats = ws.snapshot(settings)
    committed = repo.resolve_single(settings, "@")

    path.unlink()
    repo, _stats = ws.snapshot(settings)
    empty = repo.resolve_single(settings, "@")
    ws.check_out(repo, empty)
    assert not path.exists()

    ws.check_out(repo, repo.get_commit(committed.id))
    assert path.read_bytes() == CRLF_CONTENT


def test_input_only_mode_does_not_restore_crlf_on_checkout(tmp_path, monkeypatch):
    """`"input"` normalizes CRLF -> LF going into the store, but does *not*
    convert back on checkout -- distinct from `"input-output"`.
    """
    ws, repo, settings, workspace_root = _workspace_with_eol_mode(tmp_path, monkeypatch, "input")
    path = workspace_root / "f.txt"
    path.write_bytes(CRLF_CONTENT)
    repo, _stats = ws.snapshot(settings)
    committed = repo.resolve_single(settings, "@")

    path.unlink()
    repo, _stats = ws.snapshot(settings)
    empty = repo.resolve_single(settings, "@")
    ws.check_out(repo, empty)

    ws.check_out(repo, repo.get_commit(committed.id))
    assert path.read_bytes() == LF_CONTENT


def test_none_mode_round_trips_crlf_untouched(tmp_path, monkeypatch):
    ws, repo, settings, workspace_root = _workspace_with_eol_mode(tmp_path, monkeypatch, "none")
    path = workspace_root / "f.txt"
    path.write_bytes(CRLF_CONTENT)
    repo, _stats = ws.snapshot(settings)
    committed = repo.resolve_single(settings, "@")

    path.unlink()
    repo, _stats = ws.snapshot(settings)
    empty = repo.resolve_single(settings, "@")
    ws.check_out(repo, empty)

    ws.check_out(repo, repo.get_commit(committed.id))
    assert path.read_bytes() == CRLF_CONTENT
