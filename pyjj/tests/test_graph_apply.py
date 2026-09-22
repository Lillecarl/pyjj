"""What `graph apply` refuses, and what it leaves behind when it does.

Every refusal here has the same obligation: the repository is exactly
as it was. So each test records the commit ids before and compares
them after, rather than trusting the message.

The immutable set arrives through `JJ_CONFIG`. `config set --repo`
writes somewhere the revset loader does not read back, which is a
separate bug; going through the environment keeps these tests about
`graph apply`.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


def _run(root, *args, env=None):
    environment = os.environ.copy()
    environment.update(JJ_ENV)
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
        capture_output=True, text=True, env=environment,
    )


def _init(root):
    """`git init` cannot take `-R`: the repository it names does not
    exist yet."""
    environment = os.environ.copy()
    environment.update(JJ_ENV)
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "git", "init"],
        capture_output=True, text=True, env=environment, cwd=str(root),
    )
    assert result.returncode == 0, result.stderr


def _state(root, env=None) -> str:
    """Every commit id in the repository, as one comparable string."""
    result = _run(root, "log", "-r", "all() ~ root()", "--no-graph",
                  "-T", "{{ change_id_short }}={{ commit_id_short_raw }};",
                  env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def topics(tmp_path):
    """`main` with two topics off it, plus a commit keeping `b` alive.

    `shared` decides whether the two topics touch the same file, which
    is what makes stacking one on the other conflict.
    """
    def build(shared: bool):
        root = tmp_path / ("shared" if shared else "separate")
        root.mkdir()
        _init(root)
        (root / "base.txt").write_text("base\n")
        _run(root, "commit", "-m", "base")
        _run(root, "bookmark", "create", "main", "-r", "@-")
        for topic in ("a", "b"):
            _run(root, "new", "main", "-m", f"topic {topic}")
            name = "shared.txt" if shared else f"{topic}.txt"
            (root / name).write_text(topic + "\n")
            _run(root, "bookmark", "create", topic, "-r", "@")
        _run(root, "new", "b", "-m", "keepalive")
        return root
    return build


def _graph(root, path: Path, env=None) -> None:
    result = _run(root, "log", "-r", "all() ~ root()", "--dot",
                  "--dot-key", "change_id", "-T", "{{ description }}",
                  env=env)
    assert result.returncode == 0, result.stderr
    path.write_text(result.stdout)


def _stack_a_on_b(src: Path, dst: Path) -> None:
    """Rewrite the graph so `a` sits on `b` instead of on `main`."""
    import pygraphviz
    graph = pygraphviz.AGraph(filename=str(src))

    def named(bookmark):
        return next(n for n in graph.nodes()
                    if n.attr["bookmarks"] == bookmark)

    graph.remove_edge(named("a"), named("main"))
    graph.add_edge(named("a"), named("b"))
    graph.write(str(dst))


def test_apply_reshapes_and_is_idempotent(topics, tmp_path):
    root = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current)
    _stack_a_on_b(current, target)

    first = _run(root, "graph", "apply", str(target))
    assert first.returncode == 0, first.stderr
    assert "Reshaped" in first.stdout

    again = _run(root, "graph", "apply", str(target))
    assert again.returncode == 0, again.stderr
    assert "Nothing to do" in again.stdout


def test_dry_run_writes_nothing(topics, tmp_path):
    root = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current)
    _stack_a_on_b(current, target)

    before = _state(root)
    result = _run(root, "graph", "apply", "--dry-run", str(target))
    assert result.returncode == 0, result.stderr
    assert "would rebase" in result.stdout
    assert _state(root) == before


def test_a_conflict_rolls_the_whole_reshape_back(topics, tmp_path):
    """The two topics touch one file, so stacking them conflicts. A
    graph describes topology and cannot have asked for that."""
    root = topics(shared=True)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current)
    _stack_a_on_b(current, target)

    before = _state(root)
    result = _run(root, "graph", "apply", str(target))
    assert result.returncode == 1
    assert "in conflict" in result.stderr
    assert "--allow-conflicts" in result.stderr
    assert _state(root) == before, "the rollback did not restore the repository"


def test_allow_conflicts_keeps_the_result(topics, tmp_path):
    root = topics(shared=True)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current)
    _stack_a_on_b(current, target)

    result = _run(root, "graph", "apply", "--allow-conflicts", str(target))
    assert result.returncode == 0, result.stderr
    conflicted = _run(root, "log", "-r", "conflicts()", "--no-graph",
                      "-T", "{{ change_id_short }}")
    assert conflicted.stdout.strip(), "nothing ended up conflicted"


def test_an_immutable_commit_is_refused(topics, tmp_path):
    root = topics(shared=False)
    config = tmp_path / "immutable.toml"
    config.write_text('revset-aliases."immutable_heads()" = "a"\n')
    env = {"JJ_CONFIG": str(config)}

    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, env=env)
    _stack_a_on_b(current, target)

    before = _state(root, env=env)
    result = _run(root, "graph", "apply", str(target), env=env)
    assert result.returncode == 1
    assert "immutable" in result.stderr
    assert _state(root, env=env) == before


def test_ignore_immutable_lets_it_through(topics, tmp_path):
    root = topics(shared=False)
    config = tmp_path / "immutable.toml"
    config.write_text('revset-aliases."immutable_heads()" = "a"\n')
    env = {"JJ_CONFIG": str(config)}

    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, env=env)
    _stack_a_on_b(current, target)

    before = _state(root, env=env)
    result = _run(root, "graph", "apply", "--ignore-immutable", str(target),
                  env=env)
    assert result.returncode == 0, result.stderr
    assert _state(root, env=env) != before


def test_a_cycle_is_refused_before_anything_is_written(topics, tmp_path):
    root = topics(shared=False)
    current = tmp_path / "c.dot"
    _graph(root, current)

    import pygraphviz
    graph = pygraphviz.AGraph(filename=str(current))

    def named(bookmark):
        return next(n for n in graph.nodes()
                    if n.attr["bookmarks"] == bookmark)

    a, b = named("a"), named("b")
    graph.add_edge(a, b)
    graph.add_edge(b, a)
    target = tmp_path / "cycle.dot"
    graph.write(str(target))

    before = _state(root)
    result = _run(root, "graph", "apply", str(target))
    assert result.returncode == 2
    assert "cycle" in result.stderr
    assert _state(root) == before


def test_a_node_naming_no_commit_is_refused(topics, tmp_path):
    root = topics(shared=False)
    target = tmp_path / "unknown.dot"
    target.write_text(
        'digraph g { "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz" -> "main"; }')

    before = _state(root)
    result = _run(root, "graph", "apply", str(target))
    assert result.returncode in (1, 2)
    assert _state(root) == before


def test_an_unreadable_graph_is_refused(topics, tmp_path):
    root = topics(shared=False)
    target = tmp_path / "bad.dot"
    target.write_text("this is not a graph {{{")

    before = _state(root)
    result = _run(root, "graph", "apply", str(target))
    assert result.returncode == 2
    assert _state(root) == before


def test_a_missing_file_is_refused(topics, tmp_path):
    root = topics(shared=False)
    result = _run(root, "graph", "apply", str(tmp_path / "nope.dot"))
    assert result.returncode == 2
    assert "cannot read" in result.stderr
