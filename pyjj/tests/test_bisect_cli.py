"""Tests for `pyjj bisect run`.

Drives the real CLI as a subprocess against a linear history where each
commit writes its index to `n.txt`. The evaluation command reads that
file, so the good/bad boundary is deterministic.

Predicate scripts live *outside* the workspace on purpose. Each step
checks out a different tree, so a script written inside the repo
disappears after the first checkout and the command then fails for the
wrong reason.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


CUTOFF = 6
TOTAL = 10


@pytest.fixture(autouse=True)
def _needs_jj():
    if not (os.environ.get("PYJJ_PARITY_JJ") or shutil.which("jj")):
        pytest.skip("no jj binary on PATH")


@pytest.fixture
def bisect_repo(tmp_path_factory):
    """A line of commits where `n.txt` holds the commit's index.

    Returns `(root, env, ids)` with ids oldest-first.
    """
    root = tmp_path_factory.mktemp("repo")
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        JJ_USER="tester",
        JJ_EMAIL="tester@example.com",
        NO_COLOR="1",
    )
    jj = os.environ.get("PYJJ_PARITY_JJ") or "jj"
    if os.environ.get("PYJJ_PARITY_JJ"):
        env["PATH"] = os.pathsep.join([str(Path(jj).parent), env.get("PATH", "")])

    def run_jj(*args):
        result = subprocess.run([jj, *args], cwd=root, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result

    run_jj("git", "init", ".")
    ids = []
    for i in range(TOTAL):
        (root / "n.txt").write_text(str(i))
        run_jj("describe", "-m", f"c{i}")
        out = run_jj("--no-pager", "log", "--no-graph", "-r", "@",
                     "-T", 'commit_id ++ "\n"')
        ids.append(out.stdout.strip())
        run_jj("new")

    return root, env, ids


@pytest.fixture
def scripts(tmp_path_factory):
    """A directory for predicate scripts, outside any workspace."""
    return tmp_path_factory.mktemp("scripts")


def write_script(scripts, name, body):
    path = scripts / name
    path.write_text(body)
    return str(path)


def run_pyjj(root, env, *args):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", *args],
        cwd=root, env=env, capture_output=True, text=True,
    )


def test_bisect_run_finds_the_first_bad_revision(bisect_repo, scripts):
    root, env, ids = bisect_repo
    script = write_script(scripts, "check.py",
                          "import pathlib, sys\n"
                          "n = int(pathlib.Path('n.txt').read_text())\n"
                          f"sys.exit(1 if n >= {CUTOFF} else 0)\n")

    result = run_pyjj(root, env, "bisect", "run", "--range", "root()..@",
                      sys.executable, script)
    assert result.returncode == 0, result.stderr + result.stdout
    # The exact revision, not just the message -- otherwise a broken
    # predicate would still "find" something and pass.
    assert ids[CUTOFF][:8] in result.stdout, result.stdout
    assert "The first bad revision is:" in result.stdout
    assert "Bisecting:" in result.stdout
    assert "Now evaluating:" in result.stdout
    assert "Search complete." in result.stdout
    assert "jj op restore " in result.stdout


def test_bisect_run_sets_the_target_env_var(bisect_repo, scripts, tmp_path_factory):
    """`$JJ_BISECT_TARGET` carries the commit id being tested."""
    root, env, ids = bisect_repo
    log = tmp_path_factory.mktemp("targets") / "targets.txt"
    script = write_script(
        scripts, "record.py",
        "import os, pathlib, sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        "    f.write(os.environ['JJ_BISECT_TARGET'] + '\\n')\n"
        "n = int(pathlib.Path('n.txt').read_text())\n"
        f"sys.exit(1 if n >= {CUTOFF} else 0)\n",
    )
    result = run_pyjj(root, env, "bisect", "run", "--range", "root()..@",
                      sys.executable, script)
    assert result.returncode == 0, result.stderr + result.stdout
    recorded = log.read_text().split()
    assert recorded, "evaluation command never ran"
    assert all(len(line) == 40 for line in recorded), recorded
    # Every id it tested is one of the commits in the range.
    assert set(recorded) <= set(ids), recorded


def test_bisect_run_requires_a_command(bisect_repo):
    root, env, _ids = bisect_repo
    result = run_pyjj(root, env, "bisect", "run", "--range", "root()..@")
    assert result.returncode != 0
    assert "Command argument is required" in result.stderr


def test_bisect_run_aborts_on_127(bisect_repo, scripts):
    """Exit 127 means 'command not found' and stops the bisection."""
    root, env, _ids = bisect_repo
    script = write_script(scripts, "abort.py", "import sys\nsys.exit(127)\n")
    result = run_pyjj(root, env, "bisect", "run", "--range", "root()..@",
                      sys.executable, script)
    assert result.returncode != 0
    assert "aborting bisection" in result.stdout
    assert "Bisection aborted" in result.stderr


def test_bisect_run_skip_is_not_bad(bisect_repo, scripts):
    """Exit 125 skips rather than marking the revision bad."""
    root, env, _ids = bisect_repo
    script = write_script(scripts, "skip.py", "import sys\nsys.exit(125)\n")
    result = run_pyjj(root, env, "bisect", "run", "--range", "root()..@",
                      sys.executable, script)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "could not be determined" in result.stdout


def test_bisect_run_find_good_inverts(bisect_repo, scripts):
    """`--find-good` looks for the first good revision instead."""
    root, env, ids = bisect_repo
    script = write_script(scripts, "inverted.py",
                          "import pathlib, sys\n"
                          "n = int(pathlib.Path('n.txt').read_text())\n"
                          f"sys.exit(0 if n >= {CUTOFF} else 1)\n")
    result = run_pyjj(root, env, "bisect", "run", "--find-good",
                      "--range", "root()..@", sys.executable, script)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "The first good revision is:" in result.stdout
    assert ids[CUTOFF][:8] in result.stdout, result.stdout
