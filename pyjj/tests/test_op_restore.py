"""`op restore` / `op show` accept a unique operation-id prefix.

jj resolves short ids everywhere an operation is named; pyjj's binding
takes full hex only, so the CLI matches a prefix against the reachable
log itself. Found by a blind CTF solver: `op show <12-char>` failed
with "operation not found".
"""

import os
import subprocess
import sys

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


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


def _op_ids(root, home):
    """Operation ids, newest first."""
    result = _run(root, "op", "log", "--no-graph", "-T", "{{ id }}",
                  home=home)
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def _commits(root, home):
    result = _run(root, "log", "-r", "all() ~ root()", "--no-graph",
                  "-T", "{{ description }};", home=home)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_restore_by_prefix_round_trips_state(tmp_path):
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _init(root, home)
    (root / "a.txt").write_text("a\n")
    _run(root, "commit", "-m", "first", home=home)
    before = _op_ids(root, home)[0]
    (root / "b.txt").write_text("b\n")
    _run(root, "commit", "-m", "second", home=home)
    assert "second" in _commits(root, home)

    restored = _run(root, "op", "restore", before[:12], home=home)
    assert restored.returncode == 0, restored.stderr
    assert "second" not in _commits(root, home)


def test_show_by_prefix_names_the_operation(tmp_path):
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _init(root, home)
    (root / "a.txt").write_text("a\n")
    _run(root, "commit", "-m", "first", home=home)
    head = _op_ids(root, home)[0]

    shown = _run(root, "op", "show", head[:12], home=home)
    assert shown.returncode == 0, shown.stderr


def test_an_unknown_operation_is_refused(tmp_path):
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    _init(root, home)

    result = _run(root, "op", "restore", "0" * 64, home=home)
    assert result.returncode == 1
