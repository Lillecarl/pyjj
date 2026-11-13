"""What `git push` reports, and where.

A push whose expected remote position is stale must say so and exit 1.
jj writes its whole push report to stderr; pyjj wrote the
`Changes to push` lines to stdout, after any error, so a command piped
through `tail` looked like a successful push.
"""

import os
import subprocess
import sys

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


@pytest.fixture
def clones(tmp_path):
    """Two clones of one bare remote, both with `main` tracked."""
    home = tmp_path / "home"
    (home / "jj").mkdir(parents=True)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    env = os.environ.copy()
    env.update(JJ_ENV)
    env["XDG_CONFIG_HOME"] = str(home)

    def run(cwd, *args):
        return subprocess.run([sys.executable, "-m", "pyjj_cli", *args],
                              capture_output=True, text=True, env=env, cwd=str(cwd))

    def ok(cwd, *args):
        result = run(cwd, *args)
        assert result.returncode == 0, result.stderr
        return result

    seed = tmp_path / "seed"
    seed.mkdir()
    ok(seed, "git", "init")
    (seed / "f.txt").write_text("zero\n")
    ok(seed, "commit", "-m", "zero")
    ok(seed, "bookmark", "create", "main", "-r", "@-")
    ok(seed, "git", "remote", "add", "origin", str(bare))
    ok(seed, "git", "push", "--bookmark", "main")
    for name in ("a", "b"):
        ok(tmp_path, "git", "clone", str(bare), name)
        # The bare remote's HEAD is not `main`, so the clone tracks nothing.
        ok(tmp_path / name, "bookmark", "track", "main@origin")
        ok(tmp_path / name, "new", "main")
    run.ok = ok
    run.a, run.b = tmp_path / "a", tmp_path / "b"
    return run


def _advance(run, repo, text):
    (repo / "f.txt").write_text(text)
    run.ok(repo, "commit", "-m", text.strip())
    run.ok(repo, "bookmark", "set", "main", "-r", "@-")


def test_a_push_records_the_new_remote_position(clones):
    _advance(clones, clones.a, "one\n")
    result = clones.ok(clones.a, "git", "push", "--bookmark", "main")
    assert result.stdout == ""
    assert result.stderr == "Changes to push to origin:\n  Move forward bookmark main\n"
    main, origin = (clones.ok(clones.a, "log", "-r", rev, "--no-graph",
                              "-T", "{{ commit_id }}").stdout for rev in ("main", "main@origin"))
    assert main == origin
    op = clones.ok(clones.a, "op", "log", "-n", "1", "--no-graph", "-T", "{{ subject }}\n")
    assert op.stdout == "push bookmark main to git remote origin\n"


def test_a_stale_push_is_refused_loudly(clones):
    """`b` still expects the remote at `zero` after `a` pushed `one`."""
    _advance(clones, clones.a, "one\n")
    clones.ok(clones.a, "git", "push", "--bookmark", "main")
    _advance(clones, clones.b, "two\n")
    ops_before = clones.ok(clones.b, "op", "log", "--no-graph", "-T", "{{ id }}\n").stdout

    result = clones(clones.b, "git", "push", "--bookmark", "main")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Changes to push to origin:\n"
        "  Move forward bookmark main\n"
        "Warning: The following references unexpectedly moved on the remote:\n"
        "  main (reason: stale info)\n"
        "Hint: Try fetching from the remote, then make the bookmark point to "
        "where you want it to be, and push again.\n"
        "Error: Failed to push some bookmarks\n"
    )
    assert clones.ok(clones.b, "op", "log", "--no-graph", "-T", "{{ id }}\n").stdout == ops_before
