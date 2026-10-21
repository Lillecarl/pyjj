"""What `UserSettings` reports while it loads config."""

import pytest

import pyjj


def test_an_alias_that_does_not_load_is_a_warning():
    settings = pyjj.UserSettings(load_config=False).with_command_args(
        [("config", 'revset-aliases."bad(" = "x"')])
    assert any("Failed to load `revset-aliases.bad(`" in w for w in settings.warnings)
    assert pyjj.UserSettings(load_config=False).warnings == []


def test_an_alias_table_of_the_wrong_type_is_an_error():
    with pytest.raises(pyjj.ConfigError, match="Expected a table"):
        pyjj.UserSettings(load_config=False).with_command_args(
            [("config", 'revset-aliases = "x"')])


def test_layer_keys_are_quoted_as_toml():
    settings = pyjj.UserSettings(load_config=False).with_command_args(
        [("config", 'aliases."my.alias" = ["log"]')])
    names = {name for layer in settings.config_layers() for name in layer.entries}
    assert 'aliases."my.alias"' in names


def test_layering_more_args_does_not_repeat_a_warning():
    base = pyjj.UserSettings(load_config=False).with_command_args(
        [("config", 'revset-aliases."bad(" = "x"')])
    layered = base.with_command_args([("config", "ui.color = 'never'")])
    assert layered.warnings == base.warnings
    assert len(base.warnings) == 1
