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
