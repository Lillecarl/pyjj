"""Tests for pyjjui.config: the persisted "don't ask again ever"
preference file. Isolated per-test by conftest.py's autouse
pyjjui_config_dir fixture -- never touches a real ~/.config/pyjjui.
"""

from pyjjui import config


def test_load_skipped_confirmations_returns_empty_set_when_no_file():
    assert config.load_skipped_confirmations() == set()


def test_persist_then_load_roundtrips():
    config.persist_skip_confirmation("squash")

    assert config.load_skipped_confirmations() == {"squash"}


def test_persist_accumulates_multiple_actions():
    config.persist_skip_confirmation("squash")
    config.persist_skip_confirmation("rebase")

    assert config.load_skipped_confirmations() == {"squash", "rebase"}


def test_persist_is_idempotent():
    config.persist_skip_confirmation("squash")
    config.persist_skip_confirmation("squash")

    assert config.load_skipped_confirmations() == {"squash"}


def test_load_skipped_confirmations_ignores_a_corrupt_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PYJJUI_CONFIG_DIR", str(tmp_path))
    (tmp_path / "confirmations.json").write_text("not json{{{")

    assert config.load_skipped_confirmations() == set()
