"""The CLI says what it did: moves report, conflicts show in `log`.

`bookmark move` used to print `No bookmarks to update.` even when the
names matched (just already there), and print nothing at all on a real
move. `log` showed no conflict marker, so a `grep -i conflict` found
nothing on conflicted commits. Both sent a blind session the wrong way.
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
