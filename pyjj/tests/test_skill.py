"""`pyjj skill path`: print the installed SKILL.md path.

The skill ships at share/skills/pyjj-cli/<name>/SKILL.md, but no
running process can guess that prefix, so the build records its own
skill directory beside the installed package (with a source-tree
fallback for checkouts). These tests hold both resolutions.
"""

import os
import subprocess
import sys


def _env(home):
    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(home)
    return environment


def _run(*args, home):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", *args],
        capture_output=True, text=True, env=_env(home),
    )


def test_skill_path_prints_an_existing_file(tmp_path):
    result = _run("skill", "path", home=tmp_path)
    assert result.returncode == 0, result.stderr
    path = result.stdout.strip()
    assert path.endswith("SKILL.md")
    assert os.path.isfile(path)


def test_skill_path_defaults_to_pyjj(tmp_path):
    named = _run("skill", "path", "pyjj", home=tmp_path)
    bare = _run("skill", "path", home=tmp_path)
    assert named.returncode == 0, named.stderr
    assert bare.stdout == named.stdout


def test_bare_skill_prints_the_path(tmp_path):
    result = _run("skill", home=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("SKILL.md")


def test_an_unknown_skill_is_refused(tmp_path):
    result = _run("skill", "path", "no-such-skill", home=tmp_path)
    assert result.returncode == 1
    assert "no-such-skill" in result.stderr
