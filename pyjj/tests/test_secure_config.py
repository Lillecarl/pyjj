"""Tests for the per-repo config bookkeeping behind `jj config gc`.

pyjj deliberately does not read repo-level config values -- see
`pyjj-bindings/src/config.rs` for why. These calls do not: they read the
repo path a config directory records, and delete a directory whose repo
is gone.
"""

from pathlib import Path

import pytest

import pyjj


def test_repo_configs_root_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert Path(pyjj.repo_configs_root_dir()) == tmp_path / "jj" / "repos"


def test_repo_configs_root_dir_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Path(pyjj.repo_configs_root_dir()) == tmp_path / ".config" / "jj" / "repos"


def test_a_directory_with_no_metadata_records_no_path(tmp_path):
    """`jj config gc` skips these rather than guessing, and so must we."""
    (tmp_path / "empty").mkdir()
    assert pyjj.repo_config_repo_path(str(tmp_path / "empty")) is None


def test_a_missing_directory_records_no_path(tmp_path):
    assert pyjj.repo_config_repo_path(str(tmp_path / "absent")) is None


def test_remove_repo_config_dir_deletes_the_known_files(tmp_path):
    config_dir = tmp_path / "0123456789abcdef0123"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("[ui]\n")
    (config_dir / "metadata.binpb").write_bytes(b"")
    pyjj.remove_repo_config_dir(str(config_dir))
    assert not config_dir.exists()


def test_remove_repo_config_dir_refuses_a_stranger(tmp_path):
    """Non-recursive on purpose: a file someone put there is not ours."""
    config_dir = tmp_path / "0123456789abcdef0123"
    config_dir.mkdir()
    (config_dir / "notes.txt").write_text("mine\n")
    with pytest.raises(pyjj.JjError):
        pyjj.remove_repo_config_dir(str(config_dir))
    assert (config_dir / "notes.txt").exists()
