"""Unit tests for UserSettings."""

import pyjj_bindings as b


def test_user_settings_default_construction():
    settings = b.UserSettings()
    assert isinstance(settings.user_name, str)
    assert isinstance(settings.user_email, str)
    assert isinstance(settings.operation_hostname, str)
    assert isinstance(settings.operation_username, str)


def test_user_settings_signature():
    settings = b.UserSettings()
    sig = settings.signature()
    assert sig.name == settings.user_name
    assert sig.email == settings.user_email


def test_user_settings_repr():
    settings = b.UserSettings()
    assert settings.user_name in repr(settings)
    assert settings.user_email in repr(settings)


def test_config_layers_carry_source_path_and_entries():
    layers = b.UserSettings().config_layers()
    assert layers, "even a bare machine has default layers"
    sources = [layer.source for layer in layers]
    assert "default" in sources
    for layer in layers:
        assert isinstance(layer.source, str)
        assert layer.path is None or isinstance(layer.path, str)
        assert isinstance(layer.entries, dict)
        for name, value in layer.entries.items():
            assert isinstance(name, str) and name
            # Values render decor-free: a leading space would be
            # whitespace leaked from between the key and the value.
            # TOML-syntax values never start with any (quoted,
            # bracketed or bare).
            assert value and not value[0].isspace(), (name, value)
