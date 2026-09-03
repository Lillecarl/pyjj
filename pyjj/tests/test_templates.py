"""Tests for the `pyjj templates` helper and `pyjj.templates.*` Jinja in log.

These tests drive the CLI as a subprocess, because the templates commands
shell out to `jj config`. `jj config set --repo` writes into the user's
config directory, not into the repo (see `_jj_config_get` in
`pyjj_cli.commands.common`), so every run needs its own HOME and
XDG_CONFIG_HOME. Without that the tests write to the developer's real
config.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pyjj_cli.commands.templates.templates_set import _validate_template


@pytest.fixture
def cli(tmp_path_factory, workspace):
    """Run `pyjj` in the fixture workspace with an isolated config.

    HOME must sit outside the workspace. `jj config set --repo` writes
    under it, and anything written inside the workspace would show up as a
    working-copy change and force a re-snapshot on the next command.
    """
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir(parents=True)

    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        JJ_USER="tester",
        JJ_EMAIL="tester@example.com",
        # _use_color() checks NO_COLOR first, so this wins over any
        # FORCE_COLOR the developer's shell exports.
        NO_COLOR="1",
    )
    # The commands shell out to `jj` from PATH. Use the pinned binary the
    # bindings were built against when the harness names one.
    pinned = os.environ.get("PYJJ_PARITY_JJ")
    if pinned:
        env["PATH"] = os.pathsep.join(
            [str(Path(pinned).parent), env.get("PATH", "")]
        )

    root = Path(workspace.workspace_root)

    def run(*args, **overrides):
        return subprocess.run(
            [sys.executable, "-m", "pyjj_cli", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            env={**env, **overrides},
        )

    return run


@pytest.fixture(autouse=True)
def _needs_jj():
    """Skip when no `jj` binary is reachable -- these tests shell out."""
    if not (os.environ.get("PYJJ_PARITY_JJ") or shutil.which("jj")):
        pytest.skip("no jj binary on PATH")


def test_validate_template_accepts_known_vars():
    ok, msg = _validate_template("{{ author_name }} -- {{ description }}")
    assert ok, msg


def test_validate_template_rejects_unknown():
    ok, msg = _validate_template("{{ unknown_var }}")
    assert not ok
    assert "unknown_var" in msg


def test_templates_set_get_list_unset_repo(cli):
    result = cli("templates", "set", "--repo", "log", "hello {{ author_name }}")
    assert result.returncode == 0, result.stderr
    assert "pyjj.templates.log" in result.stdout

    result = cli("templates", "get", "log")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello {{ author_name }}\n"

    result = cli("templates", "list", "--repo")
    assert result.returncode == 0, result.stderr
    assert "pyjj.templates.log" in result.stdout

    # `set` validates before it writes.
    result = cli("templates", "set", "--repo", "bad", "hi {{ unknown }}")
    assert result.returncode != 0
    assert "unknown" in result.stderr.lower()
    assert cli("templates", "get", "bad").returncode != 0

    result = cli("templates", "unset", "--repo", "log")
    assert result.returncode == 0, result.stderr
    assert cli("templates", "get", "log").returncode != 0


def test_templates_get_reads_repo_config(cli):
    """The point of `_jj_config_get`: UserSettings cannot see repo config."""
    assert cli("templates", "set", "--repo", "fromrepo", "x {{ description }}").returncode == 0
    result = cli("templates", "get", "fromrepo")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "x {{ description }}\n"


def test_templates_set_keeps_value_verbatim(cli):
    """Values are stored as TOML but must come back unquoted and intact."""
    value = "{{ author_name }} 'quoted' \"double\" | {{ description }}"
    assert cli("templates", "set", "--repo", "quoting", value).returncode == 0
    result = cli("templates", "get", "quoting")
    assert result.returncode == 0, result.stderr
    assert result.stdout == value + "\n"


def test_templates_edit_with_editor(cli):
    assert cli("templates", "set", "--repo", "editme", "original {{ description }}").returncode == 0

    # An editor that rewrites the file in place.
    result = cli(
        "templates", "edit", "--repo", "editme",
        JJ_EDITOR="sed -i s/original/edited/",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Updated" in result.stdout

    result = cli("templates", "get", "editme")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "edited {{ description }}\n"


def test_templates_edit_empty_aborts(cli):
    assert cli("templates", "set", "--repo", "emptytest", "keep {{ description }}").returncode == 0

    result = cli(
        "templates", "edit", "--repo", "emptytest", JJ_EDITOR="truncate -s 0"
    )
    assert result.returncode != 0
    assert "empty" in result.stderr.lower()

    # The stored value must survive an aborted edit.
    result = cli("templates", "get", "emptytest")
    assert result.stdout == "keep {{ description }}\n"


def test_log_uses_pyjj_templates_log(cli):
    """With no -T, `log` picks up `pyjj.templates.log` from repo config."""
    plain = cli("log", "-n", "1")
    assert plain.returncode == 0, plain.stderr

    assert cli(
        "templates", "set", "--repo", "log", "TPL {{ author_name }}|{{ description }}"
    ).returncode == 0

    result = cli("log", "-n", "1")
    assert result.returncode == 0, result.stderr
    # The `workspace` fixture builds the repo with `load_config=False`, so
    # the commit has no author name and no description.
    assert "TPL |(no description set)" in result.stdout
    assert result.stdout != plain.stdout


def test_log_named_template_via_dash_t(cli):
    assert cli("templates", "set", "--repo", "mycool", "COOL {{ commit_id_short_raw }}").returncode == 0

    result = cli("log", "-n", "1", "-T", "mycool")
    assert result.returncode == 0, result.stderr
    assert "COOL " in result.stdout
    # `commit_id_short_raw` is the first 8 hex characters of the commit id.
    marker = result.stdout.split("COOL ", 1)[1][:8]
    assert len(marker) == 8
    assert all(c in "0123456789abcdef" for c in marker), marker


def test_log_unknown_named_template_is_literal(cli):
    """A bare name with no matching config stays a raw Jinja template."""
    result = cli("log", "-n", "1", "-T", "nosuchtemplate")
    assert result.returncode == 0, result.stderr
    assert "nosuchtemplate" in result.stdout


def test_log_template_builtin_and_custom(cli):
    result = cli("log", "-n", "1", "-T", "builtin_log_oneline")
    assert result.returncode == 0, result.stderr

    result = cli("log", "-n", "1", "-T", "{{ author_email }}")
    assert result.returncode == 0, result.stderr


def test_log_template_rejects_unknown_variable(cli):
    """StrictUndefined makes a bad template fail loudly, not render empty."""
    result = cli("log", "-n", "1", "-T", "{{ nope_not_a_var }}")
    assert result.returncode != 0
    assert "nope_not_a_var" in result.stderr
