"""Unit tests for UserSettings."""

import pyjj_bindings as b


def _bare():
    # Hermetic: no machine config, so the command layers are the only
    # thing under test.
    return b.UserSettings(load_config=False)


def test_command_args_override_and_leave_the_base_untouched():
    base = _bare()
    assert base.get_string("user.name") == ""
    layered = base.with_command_args([("config", "user.name=CmdUser")])
    assert layered.get_string("user.name") == "CmdUser"
    assert base.get_string("user.name") == ""


def test_command_args_resolve_in_argv_order_across_kinds(tmp_path):
    first = tmp_path / "first.toml"
    first.write_text('user.name = "FileUser"\nui.color = "always"\n')
    settings = _bare().with_command_args([
        ("config", "user.name=CmdUser"),
        ("config-file", str(first)),
        ("config", "ui.color=never"),
    ])
    # The file came after the first pair, the second pair after the
    # file: each flag wins over every flag before it.
    assert settings.get_string("user.name") == "FileUser"
    assert settings.get_string("ui.color") == "never"
    assert settings.with_command_args(
        [("config", "user.name=One"), ("config", "user.name=Two")]
    ).get_string("user.name") == "Two"


def test_command_args_value_falls_back_to_bare_string():
    settings = _bare()
    assert settings.with_command_args(
        [("config", "user.name=Foo")]
    ).get_string("user.name") == "Foo"
    assert settings.with_command_args(
        [("config", "user.name=a=b")]
    ).get_string("user.name") == "a=b"
    assert settings.with_command_args(
        [("config", "debug.randomness-seed=5")]
    ).get_int("debug.randomness-seed") == 5
    assert settings.with_command_args(
        [("config", "ui.color=true")]
    ).get_bool("ui.color") is True


def test_command_args_layers_carry_cli_source_and_path(tmp_path):
    first = tmp_path / "first.toml"
    first.write_text('user.name = "FileUser"\n')
    layers = _bare().with_command_args([
        ("config", "user.name=CmdUser"),
        ("config-file", str(first)),
    ]).config_layers()
    cli = [layer for layer in layers if layer.source == "cli"]
    assert [layer.path for layer in cli] == [None, str(first)]
    assert cli[1].entries["user.name"] == '"FileUser"'


def test_command_args_missing_equals():
    try:
        _bare().with_command_args([("config", "user.name")])
    except Exception as e:
        assert str(e) == "--config must be specified as NAME=VALUE"
    else:
        raise AssertionError("missing = must fail")


def test_command_args_bad_name():
    try:
        _bare().with_command_args([("config", "user..name=x")])
    except Exception as e:
        assert str(e) == (
            "--config name cannot be parsed\n"
            "Caused by: TOML parse error at line 1, column 6\n"
            "  |\n"
            "1 | user..name\n"
            "  |      ^\n"
            "unquoted keys cannot be empty, expected letters, numbers, `-`, `_`\n"
        ), repr(str(e))
    else:
        raise AssertionError("bad name must fail")


def test_command_args_bad_value():
    try:
        _bare().with_command_args([("config", 'user.name="unclosed')])
    except Exception as e:
        assert str(e) == (
            "--config value cannot be parsed\n"
            "Caused by: TOML parse error at line 1, column 10\n"
            "  |\n"
            '1 | "unclosed\n'
            "  |          ^\n"
            "invalid basic string, expected `\"`\n"
        ), repr(str(e))
    else:
        raise AssertionError("bad value must fail")


def test_command_args_missing_file():
    try:
        _bare().with_command_args(
            [("config-file", "/tmp/pyjj-test-does-not-exist.toml")])
    except Exception as e:
        assert str(e) == (
            "Failed to read configuration file\n"
            "Caused by:\n"
            "1: Cannot access /tmp/pyjj-test-does-not-exist.toml\n"
            "2: No such file or directory (os error 2)"
        ), repr(str(e))
    else:
        raise AssertionError("missing file must fail")


def test_command_args_unparseable_file_names_itself(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('user.name = "unclosed\n')
    try:
        _bare().with_command_args([("config-file", str(bad))])
    except Exception as e:
        assert str(e) == (
            "Configuration cannot be parsed as TOML document\n"
            "Caused by: TOML parse error at line 1, column 22\n"
            "  |\n"
            '1 | user.name = "unclosed\n'
            "  |                      ^\n"
            "invalid basic string, expected `\"`\n"
            "\n"
            f"Hint: Check the config file: {bad}"
        ), repr(str(e))
    else:
        raise AssertionError("unparseable file must fail")


def test_command_args_bad_seed_rejected_at_build():
    try:
        _bare().with_command_args([("config", "debug.randomness-seed=xx")])
    except Exception as e:
        assert str(e) == (
            "Invalid type or value for debug.randomness-seed\n"
            'Caused by: invalid type: string "xx", expected u64\n'
        ), repr(str(e))
    else:
        raise AssertionError("bad seed must fail")


def test_command_args_empty_input_clones():
    base = _bare()
    assert base.with_command_args([]).get_string("user.name") == ""


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
