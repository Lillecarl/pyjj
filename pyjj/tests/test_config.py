"""Tests for UserSettings' config loading (load_config=True/False)."""

import pytest

import pyjj


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path):
    """Every test in this file controls config purely via `JJ_CONFIG`/
    `JJ_USER`/`JJ_EMAIL`, set explicitly per test -- never the real machine
    config. `JJ_CONFIG` alone suppresses system *and* user config path
    resolution (see `pyjj_bindings::config`), so pointing it at an empty
    file by default keeps tests that don't care about config isolated too.
    """
    empty = tmp_path / "empty.toml"
    empty.write_text("")
    monkeypatch.setenv("JJ_CONFIG", str(empty))
    monkeypatch.delenv("JJ_USER", raising=False)
    monkeypatch.delenv("JJ_EMAIL", raising=False)


def test_load_config_false_ignores_everything(monkeypatch):
    monkeypatch.setenv("JJ_USER", "Env User")
    monkeypatch.setenv("JJ_EMAIL", "env@example.com")
    settings = pyjj.UserSettings(load_config=False)
    assert settings.user_name == ""
    assert settings.user_email == ""


def test_load_config_true_reads_jj_config_user_table(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[user]\nname = "Config User"\nemail = "config@example.com"\n')
    monkeypatch.setenv("JJ_CONFIG", str(config_file))

    settings = pyjj.UserSettings()
    assert settings.user_name == "Config User"
    assert settings.user_email == "config@example.com"


def test_env_overrides_beat_jj_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[user]\nname = "Config User"\nemail = "config@example.com"\n')
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    monkeypatch.setenv("JJ_USER", "Override User")
    monkeypatch.setenv("JJ_EMAIL", "override@example.com")

    settings = pyjj.UserSettings()
    assert settings.user_name == "Override User"
    assert settings.user_email == "override@example.com"


def test_default_constructor_loads_config(monkeypatch):
    """The bare `UserSettings()` constructor defaults to load_config=True."""
    monkeypatch.setenv("JJ_USER", "Bare Default")
    settings = pyjj.UserSettings()
    assert settings.user_name == "Bare Default"


def test_builtin_revset_aliases_available_with_config_loaded(workspace, repo):
    """`mutable()`/`trunk()`/etc. come from jj's bundled `revsets.toml`,
    which is only loaded when `load_config=True` (the default).
    """
    settings = pyjj.UserSettings()
    result = repo.revset(settings, "mutable()")
    assert isinstance(result, list)


def test_builtin_revset_aliases_unavailable_without_config(workspace, repo):
    settings = pyjj.UserSettings(load_config=False)
    with pytest.raises(pyjj.RevsetParseError):
        repo.revset(settings, "mutable()")


def test_get_string_reads_a_bundled_default():
    settings = pyjj.UserSettings()
    assert settings.get_string("revsets.log")


def test_get_string_returns_none_for_an_unset_key():
    settings = pyjj.UserSettings()
    assert settings.get_string("no.such.config.key") is None


def test_get_string_reads_a_value_from_jj_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[revsets]\nlog = "custom_revset()"\n')
    monkeypatch.setenv("JJ_CONFIG", str(config_file))

    settings = pyjj.UserSettings()
    assert settings.get_string("revsets.log") == "custom_revset()"


def test_get_string_raises_for_a_non_string_value():
    settings = pyjj.UserSettings()
    with pytest.raises(pyjj.JjError):
        settings.get_string("revsets")  # a table, not a string


def test_get_string_returns_none_without_config_loaded():
    settings = pyjj.UserSettings(load_config=False)
    assert settings.get_string("revsets.log") is None
