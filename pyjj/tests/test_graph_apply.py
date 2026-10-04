"""What `graph apply` refuses, and what it leaves behind when it does.

Every refusal here has the same obligation: the repository is exactly
as it was. So each test records the commit ids before and compares
them after, rather than trusting the message.

The immutable set is written with `config set --repo`, the way a user
would. `test_repo_config.py` covers that path itself.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


def _env(home):
    """A config home of the test's own, so the machine's real jj config
    cannot decide whether a commit is immutable."""
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
    """`git init` cannot take `-R`: the repository it names does not
    exist yet."""
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "git", "init"],
        capture_output=True, text=True, env=_env(home), cwd=str(root),
    )
    assert result.returncode == 0, result.stderr


def _state(root, home) -> str:
    """Every commit id in the repository, as one comparable string."""
    result = _run(root, "log", "-r", "all() ~ root()", "--no-graph",
                  "-T", "{{ change_id_short }}={{ commit_id_short_raw }};",
                  home=home)
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
        home = tmp_path / ("shared-home" if shared else "separate-home")
        home.mkdir()
        _init(root, home)
        (root / "base.txt").write_text("base\n")
        _run(root, "commit", "-m", "base", home=home)
        _run(root, "bookmark", "create", "main", "-r", "@-", home=home)
        for topic in ("a", "b"):
            _run(root, "new", "main", "-m", f"topic {topic}", home=home)
            name = "shared.txt" if shared else f"{topic}.txt"
            (root / name).write_text(topic + "\n")
            _run(root, "bookmark", "create", topic, "-r", "@", home=home)
        _run(root, "new", "b", "-m", "keepalive", home=home)
        return root, home
    return build


def _graph(root, path: Path, home) -> None:
    result = _run(root, "log", "-r", "all() ~ root()", "--dot",
                  "--dot-key", "change_id", "-T", "{{ description }}",
                  home=home)
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
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    first = _run(root, "graph", "apply", str(target), home=home)
    assert first.returncode == 0, first.stderr
    assert "Reshaped" in first.stdout

    again = _run(root, "graph", "apply", str(target), home=home)
    assert again.returncode == 0, again.stderr
    assert "Nothing to do" in again.stdout


def test_dry_run_writes_nothing(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    before = _state(root, home)
    result = _run(root, "graph", "apply", "--dry-run", str(target), home=home)
    assert result.returncode == 0, result.stderr
    assert "would rebase" in result.stdout
    assert _state(root, home) == before


def test_a_conflict_rolls_the_whole_reshape_back(topics, tmp_path):
    """The two topics touch one file, so stacking them conflicts. A
    graph describes topology and cannot have asked for that."""
    root, home = topics(shared=True)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 1
    assert "in conflict" in result.stderr
    assert "--allow-conflicts" in result.stderr
    assert _state(root, home) == before, "the rollback did not restore the repository"


def test_allow_conflicts_keeps_the_result(topics, tmp_path):
    root, home = topics(shared=True)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    result = _run(root, "graph", "apply", "--allow-conflicts", str(target), home=home)
    assert result.returncode == 0, result.stderr
    conflicted = _run(root, "log", "-r", "conflicts()", "--no-graph",
                      "-T", "{{ change_id_short }}", home=home)
    assert conflicted.stdout.strip(), "nothing ended up conflicted"


def _make_a_immutable(root, home):
    result = _run(root, "config", "set", "--repo",
                  'revset-aliases."immutable_heads()"', "a", home=home)
    assert result.returncode == 0, result.stderr


def test_an_immutable_commit_is_refused(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)
    _make_a_immutable(root, home)

    before = _state(root, home=home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 1
    assert "immutable" in result.stderr
    assert _state(root, home=home) == before


def test_ignore_immutable_lets_it_through(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)
    _make_a_immutable(root, home)

    before = _state(root, home=home)
    result = _run(root, "graph", "apply", "--ignore-immutable", str(target),
                  home=home)
    assert result.returncode == 0, result.stderr
    assert _state(root, home=home) != before


def test_a_cycle_is_refused_before_anything_is_written(topics, tmp_path):
    root, home = topics(shared=False)
    current = tmp_path / "c.dot"
    _graph(root, current, home=home)

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

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 2
    assert "cycle" in result.stderr
    assert _state(root, home) == before


def test_a_node_naming_no_commit_is_refused(topics, tmp_path):
    root, home = topics(shared=False)
    target = tmp_path / "unknown.dot"
    target.write_text(
        'digraph g { "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz" -> "main"; }')

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode in (1, 2)
    assert _state(root, home) == before


def test_an_unreadable_graph_is_refused(topics, tmp_path):
    root, home = topics(shared=False)
    target = tmp_path / "bad.dot"
    target.write_text("this is not a graph {{{")

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 2
    assert _state(root, home) == before


def test_a_missing_file_is_refused(topics, tmp_path):
    root, home = topics(shared=False)
    result = _run(root, "graph", "apply", str(tmp_path / "nope.dot"), home=home)
    assert result.returncode == 2
    assert "cannot read" in result.stderr


def test_success_prints_a_restore_point(topics, tmp_path):
    """The pre-apply operation id is printed, so `op restore` is one
    paste away even when the reshape worked."""
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 0, result.stderr
    match = re.search(r"op restore ([0-9a-f]+)", result.stderr)
    assert match, f"no restore point in stderr: {result.stderr!r}"

    restored = _run(root, "op", "restore", match.group(1), home=home)
    assert restored.returncode == 0, restored.stderr
    assert _state(root, home) == before


def _is_full_hex(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]+", value))


def test_json_reports_before_op(topics, tmp_path):
    import json
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _stack_a_on_b(current, target)

    result = _run(root, "graph", "apply", "--format", "json", str(target),
                  home=home)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rolled_back"] is False
    assert _is_full_hex(payload["before_op"])


def _mark_abandoned(src: Path, dst: Path, bookmark: str, value="true") -> None:
    """Set the DOT `abandon` attribute on one node's row."""
    import pygraphviz
    graph = pygraphviz.AGraph(filename=str(src))
    node = next(n for n in graph.nodes()
                if n.attr["bookmarks"] == bookmark)
    node.attr["abandon"] = value
    graph.write(str(dst))


def _describes(root, description: str, home) -> bool:
    """Whether a visible commit still carries a description. The glob
    absorbs the trailing newline `-m` stores, the way the parity
    suite's `rev()` helper does -- `exact:` would match nothing."""
    result = _run(root, "log", "--no-graph", "-r",
                  f'description(glob:"{description}*")',
                  "-T", "{{ commit_id }}", home=home)
    assert result.returncode == 0, result.stderr
    return bool(result.stdout.strip())


def _commit_id(root, revset: str, home) -> str:
    result = _run(root, "log", "--no-graph", "-r", revset,
                  "-T", "{{ commit_id }}", home=home)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_apply_abandons_a_marked_node(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _mark_abandoned(current, target, "a")

    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 0, result.stderr
    assert "Reshaped 1 commits." in result.stdout
    assert not _describes(root, "topic a", home)
    assert _describes(root, "topic b", home)


def test_apply_abandon_repoints_a_planned_child(topics, tmp_path):
    """`keepalive` points at abandoned `b` in the graph: it lands on
    `b`'s own parent `main`, the static grandparent-resolution, not a
    leftover edge at a vanished commit."""
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _mark_abandoned(current, target, "b")

    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 0, result.stderr
    assert not _describes(root, "topic b", home)
    assert _commit_id(root, 'parents(description(glob:"keepalive*"))',
                      home) == _commit_id(root, "main", home)


def test_apply_abandon_and_rebase_together(topics, tmp_path):
    """One graph both drops `a` and stacks `b`'s child `keepalive`
    onto `main`: abandons run before any rebase."""
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    import pygraphviz
    graph = pygraphviz.AGraph(filename=str(current))

    def named(bookmark=None, description=None):
        if description is not None:
            return next(n for n in graph.nodes()
                        if n.attr.get("description") == description)
        return next(n for n in graph.nodes()
                    if n.attr["bookmarks"] == bookmark)

    graph.remove_edge(named(description="keepalive"), named("b"))
    graph.add_edge(named(description="keepalive"), named("main"))
    named("a").attr["abandon"] = "true"
    graph.write(str(target))

    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 0, result.stderr
    assert not _describes(root, "topic a", home)
    assert _describes(root, "keepalive", home)


def test_a_bogus_abandon_value_is_refused(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _mark_abandoned(current, target, "a", value="sometimes")

    before = _state(root, home)
    result = _run(root, "graph", "apply", str(target), home=home)
    assert result.returncode == 2
    assert "abandon must be" in result.stderr
    assert _state(root, home) == before


def test_plan_prints_abandon_commands(topics, tmp_path):
    root, home = topics(shared=False)
    current, target = tmp_path / "c.dot", tmp_path / "t.dot"
    _graph(root, current, home=home)
    _mark_abandoned(current, target, "a")

    result = _run(root, "graph", "plan", str(target), home=home)
    assert result.returncode == 0, result.stderr
    assert "pyjj abandon " in result.stdout
    assert "1 commits reshaped" in result.stderr
