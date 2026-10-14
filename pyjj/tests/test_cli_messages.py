"""The CLI says what it did: moves report, conflicts show in `log`.

`bookmark move` used to print `No bookmarks to update.` even when the
names matched (just already there), and print nothing at all on a real
move. `log` showed no conflict marker, so a `grep -i conflict` found
nothing on conflicted commits. Both sent a blind session the wrong way.
"""

import os
import shutil
import subprocess
import sys

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1",
              JJ_TIMESTAMP="2001-02-03T04:05:06+00:00",
              JJ_OP_TIMESTAMP="2001-02-03T04:05:06+00:00",
              JJ_TZ_OFFSET_MINS="330")


def _env(home):
    environment = os.environ.copy()
    environment.update(JJ_ENV)
    environment["XDG_CONFIG_HOME"] = str(home)
    return environment


def _run(root, *args, home):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
        capture_output=True, text=True, env=_env(home),
    )


def _init(root, home):
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "git", "init"],
        capture_output=True, text=True, env=_env(home), cwd=str(root),
    )
    assert result.returncode == 0, result.stderr


def _topics(root, home, shared: bool):
    """`main` with topics `a` and `b` off it. Shared one file when
    `shared`, so stacking them conflicts."""
    _init(root, home)
    (root / "base.txt").write_text("base\n")
    _run(root, "commit", "-m", "base", home=home)
    _run(root, "bookmark", "create", "main", "-r", "@-", home=home)
    for topic in ("a", "b"):
        _run(root, "new", "main", "-m", f"topic {topic}", home=home)
        name = "shared.txt" if shared else f"{topic}.txt"
        (root / name).write_text(topic + "\n")
        _run(root, "bookmark", "create", topic, "-r", "@", home=home)


def test_move_reports_what_moved(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _topics(root, home, shared=False)
    _run(root, "new", "a", "-m", "child", home=home)

    result = _run(root, "bookmark", "move", "a", "--to", "@", home=home)
    assert result.returncode == 0, result.stderr
    assert "Moved a to " in result.stdout


def test_move_onto_where_it_sits_is_not_a_refusal(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _topics(root, home, shared=False)

    result = _run(root, "bookmark", "move", "a", "--to", "a", home=home)
    assert result.returncode == 0, result.stderr
    assert "No bookmarks to update." not in result.stdout


def test_move_with_no_match_says_so(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _topics(root, home, shared=False)

    result = _run(root, "bookmark", "move", "zzz", "--to", "b", home=home)
    assert result.returncode == 0, result.stderr
    assert "No bookmarks to update." in result.stdout


def test_log_marks_a_conflicted_commit(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _topics(root, home, shared=True)

    stacked = _run(root, "rebase", "-r", "a", "-d", "b", home=home)
    assert stacked.returncode == 0, stacked.stderr
    conflicted = _run(root, "log", "-r", "conflicts()", "--no-graph",
                      "-T", "{{ description }}", home=home)
    assert conflicted.stdout.strip(), "nothing ended up conflicted"

    shown = _run(root, "log", "-r", "conflicts()", "--no-graph",
                 home=home)
    assert shown.returncode == 0, shown.stderr
    assert "conflict" in shown.stdout.lower()


FOOTER = ("For help, see https://docs.jj-vcs.dev/latest/config/ "
          "or use `jj help -k config`.")


def _config_repo(root, home):
    root.mkdir()
    home.mkdir()
    _init(root, home)


def test_config_flag_overrides_a_key(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    result = _run(root, "--config", "user.name=CmdUser", "config", "get",
                  "user.name", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CmdUser"


def test_config_file_flag_overrides_a_key(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    overlay = tmp_path / "overlay.toml"
    overlay.write_text('user.name = "FileUser"\n')
    result = _run(root, "--config-file", str(overlay), "config", "get",
                  "user.name", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FileUser"


def test_config_flags_apply_after_the_subcommand_too(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    result = _run(root, "config", "get", "user.name",
                  "--config", "user.name=Late", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Late"


def test_config_flag_does_not_eat_a_flag_as_its_value(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    # clap reads `--color` as a new flag, not the value, so the value
    # is missing -- and `--color` must survive to be parsed itself.
    result = _run(root, "--config", "--color", "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == "Error: a value is required for '--config'\n"


def test_config_flag_without_equals_reports_like_jj(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    result = _run(root, "--config", "user.name", "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == (
        "Config error: --config must be specified as NAME=VALUE\n"
        f"{FOOTER}\n"
    )


def test_config_flag_with_bad_name_reports_like_jj(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    result = _run(root, "--config", "user..name=x", "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == (
        "Config error: --config name cannot be parsed\n"
        "Caused by: TOML parse error at line 1, column 6\n"
        "  |\n"
        "1 | user..name\n"
        "  |      ^\n"
        "unquoted keys cannot be empty, expected letters, numbers, `-`, `_`\n"
        "\n"
        f"{FOOTER}\n"
    )


def test_config_flag_with_bad_value_reports_like_jj(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    result = _run(root, "--config", 'user.name="unclosed', "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == (
        "Config error: --config value cannot be parsed\n"
        "Caused by: TOML parse error at line 1, column 10\n"
        "  |\n"
        '1 | "unclosed\n'
        "  |          ^\n"
        "invalid basic string, expected `\"`\n"
        "\n"
        f"{FOOTER}\n"
    )


def test_config_file_flag_with_missing_file_reports_like_jj(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    missing = tmp_path / "does-not-exist.toml"
    result = _run(root, "--config-file", str(missing), "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == (
        "Config error: Failed to read configuration file\n"
        "Caused by:\n"
        f"1: Cannot access {missing}\n"
        "2: No such file or directory (os error 2)\n"
        f"{FOOTER}\n"
    )


def test_config_file_flag_with_bad_toml_names_itself(tmp_path):
    root, home = tmp_path / "repo", tmp_path / "home"
    _config_repo(root, home)
    bad = tmp_path / "bad.toml"
    bad.write_text('user.name = "unclosed\n')
    result = _run(root, "--config-file", str(bad), "config", "get",
                  "user.name", home=home)
    assert result.returncode == 1
    assert result.stderr == (
        "Config error: Configuration cannot be parsed as TOML document\n"
        "Caused by: TOML parse error at line 1, column 22\n"
        "  |\n"
        '1 | user.name = "unclosed\n'
        "  |                      ^\n"
        "invalid basic string, expected `\"`\n"
        "\n"
        f"Hint: Check the config file: {bad}\n"
        f"{FOOTER}\n"
    )


def _file_repo(root, home):
    """A repo with one committed file, for the file/diff messages."""
    _init(root, home)
    (root / "base.txt").write_text("base\n")
    result = _run(root, "commit", "-m", "base", home=home)
    assert result.returncode == 0, result.stderr


def test_file_edit_unchanged_reports_nothing_changed(tmp_path, monkeypatch):
    """Saving without changes prints exactly `Nothing changed.`."""
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _file_repo(root, home)
    # `true` leaves the editor buffer untouched: the no-op path. It
    # wins over any machine VISUAL/EDITOR leaking through the env.
    monkeypatch.setenv("JJ_EDITOR", shutil.which("true"))
    result = _run(root, "file", "edit", "base.txt", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == "Nothing changed.\n"


def test_file_delete_unmatched_warns(tmp_path):
    """A pattern matching nothing reports `Nothing changed.` (stderr),
    with no warning -- matching real jj, which silently deletes what
    matches."""
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _file_repo(root, home)
    result = _run(root, "file", "delete", "nope.txt", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == "Nothing changed.\n"


def test_util_diff_missing_file_reports_cannot_access(tmp_path):
    """An unreadable path fails with jj's `Cannot access` shape."""
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _file_repo(root, home)
    result = _run(root, "util", "diff", str(root / "base.txt"),
                  str(root / "nope.txt"), home=home)
    assert result.returncode == 1
    assert result.stderr == (
        f"Error: Cannot access {root / 'nope.txt'}\n"
        "Caused by: No such file or directory (os error 2)\n"
    )
