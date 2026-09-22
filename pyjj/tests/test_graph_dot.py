"""What `graph_dot` writes and reads, and what `log --dot` prints.

The emitter takes `graph_layout`'s item shape, so these tests build the
items by hand rather than through a repository. The one test that does
drive the CLI is there to prove the labels and the rows line up.

Both directions go through libcgraph, so these assert on the graph that
comes back rather than on the bytes: exact formatting is graphviz's
business, and pinning it here would only break when graphviz changes
its mind about whitespace.
"""

import subprocess
import sys
from pathlib import Path

import pygraphviz
import pytest

from pyjj.graph_dot import DotError, parse_dot, render_dot
from pyjj_cli.commands.common import (
    CommandError,
    dot_attribute,
    select_fields,
    unpushed,
)

_CATALOGUE = ("change_id", "author", "description", "files", "diff")
_DEFAULT = ("change_id", "author", "description")


def _attrs(text: str, key: str) -> dict:
    """One node's attributes, as plain Python.

    A pygraphviz `Node` is a handle into the C graph, so it reads as
    `None` once that graph is collected. `AGraph(...).get_node(x).attr`
    in one expression leaves the graph unreferenced and returns None
    for everything, which looks exactly like an attribute that was
    never set. Keeping the graph alive until the values are copied out
    is what makes the difference.
    """
    graph = pygraphviz.AGraph(string=text)
    node = graph.get_node(key)
    return {name: value for name, value in node.attr.items()}


def test_an_id_that_starts_with_a_digit_survives():
    """A commit hex like `4e2a72e` is not a numeral, so it has to reach
    the reader as that name and not as a syntax error."""
    out = render_dot([("4e2a72e", [("3a87969", "direct")])], {})
    nodes, edges = parse_dot(out)
    assert "4e2a72e" in nodes
    assert edges["4e2a72e"] == [("3a87969", "direct")]


def test_a_label_with_a_quote_backslash_or_newline_round_trips():
    value = 'fix "the" bug \\ here\nsecond line'
    out = render_dot([("aa", [])], {"aa": value})
    assert _attrs(out, "aa")["label"] == value


def test_edge_types_survive_the_round_trip():
    items = [
        ("aa", [("bb", "direct"), ("cc", "indirect"), ("dd", "missing")]),
        ("bb", []),
        ("cc", []),
        ("dd", []),
    ]
    _nodes, edges = parse_dot(render_dot(items, {}))
    assert edges["aa"] == [("bb", "direct"), ("cc", "indirect"),
                           ("dd", "missing")]


def test_a_merges_parent_order_is_kept():
    """A merge's first parent is not interchangeable with its second,
    so the order the graph declares is the order that comes back."""
    items = [("m", [("p1", "direct"), ("p2", "direct"), ("p3", "direct")]),
             ("p1", []), ("p2", []), ("p3", [])]
    _nodes, edges = parse_dot(render_dot(items, {}))
    assert [target for target, _kind in edges["m"]] == ["p1", "p2", "p3"]


def test_a_chained_edge_reads_as_two_edges():
    """`a -> b -> c` is legal DOT and means two edges. Reading it line
    by line finds one, which is how a hand-written graph goes wrong."""
    _nodes, edges = parse_dot('digraph g { "a" -> "b" -> "c"; }')
    assert edges["a"] == [("b", "direct")]
    assert edges["b"] == [("c", "direct")]


def test_comments_subgraphs_and_unquoted_ids_are_read():
    nodes, edges = parse_dot("""
        digraph g {
          // a line comment
          /* and a block
             comment */
          subgraph cluster_x { bare_id; "quoted"; }
          bare_id -> "quoted" [style=dashed];
        }
    """)
    assert set(nodes) == {"bare_id", "quoted"}
    assert edges["bare_id"] == [("quoted", "indirect")]


def test_an_undirected_graph_is_refused():
    """It names no parents, so nothing in it can drive a rebase."""
    with pytest.raises(DotError, match="not directed"):
        parse_dot("graph g { a -- b; }")


def test_unparsable_text_is_refused():
    with pytest.raises(DotError):
        parse_dot("this is not a graph at all {{{")


def test_a_placeholder_node_is_not_a_row():
    """`(not shown)` names a commit outside the graph, so reading the
    graph back must not offer it as one of the rows."""
    out = render_dot([("aa", [("zz", "missing")])], {"aa": "A"})
    nodes, edges = parse_dot(out)
    assert nodes == ["aa"]
    assert edges["aa"] == [("zz", "missing")]


def test_a_target_outside_the_rows_gets_a_placeholder_node():
    """`log -r <subset>` reaches parents it does not draw. Without a
    declaration dot invents a node labelled with the bare hex, which
    reads as a commit that is in the graph."""
    out = render_dot([("aa", [("zz", "missing")])], {"aa": "A"})
    attrs = _attrs(out, "zz")
    assert attrs["label"] == "(not shown)"
    assert attrs["shape"] == "none"


def test_a_row_keeps_its_own_label_over_the_placeholder():
    out = render_dot([("aa", [("bb", "direct")]), ("bb", [])],
                     {"aa": "A", "bb": "B"})
    assert _attrs(out, "bb")["label"] == "B"
    assert "(not shown)" not in out


def test_fields_become_node_attributes_beside_the_label():
    out = render_dot([("aa", [])], {"aa": "A"},
                     attributes={"aa": {"change_id": "zzz",
                                        "author": "someone"}})
    attrs = _attrs(out, "aa")
    assert attrs["label"] == "A"
    assert attrs["change_id"] == "zzz"
    assert attrs["author"] == "someone"


def test_an_attribute_value_round_trips_like_a_label():
    value = 'a "b" \\ c\nd'
    out = render_dot([("aa", [])], {"aa": "A"},
                     attributes={"aa": {"diff": value}})
    assert _attrs(out, "aa")["diff"] == value


def test_a_placeholder_node_carries_no_attributes():
    """An edge target outside the rows has no row, so it has no fields
    to report -- only that it exists."""
    out = render_dot([("aa", [("zz", "missing")])], {"aa": "A"},
                     attributes={"aa": {"author": "someone"}})
    assert not _attrs(out, "zz").get("author")


def test_no_selection_gives_the_default_fields():
    assert select_fields(None, _DEFAULT, _CATALOGUE) == list(_DEFAULT)


def test_a_bare_list_replaces_the_default_set():
    assert select_fields("author,change_id", _DEFAULT, _CATALOGUE) == [
        "change_id", "author"]


def test_a_signed_list_adjusts_the_default_set():
    """This is how you keep the cheap fields and add `diff` without
    naming every other one."""
    assert select_fields("+diff", _DEFAULT, _CATALOGUE) == [
        "change_id", "author", "description", "diff"]
    assert select_fields("-author", _DEFAULT, _CATALOGUE) == [
        "change_id", "description"]


def test_mixing_the_two_forms_is_an_error():
    with pytest.raises(CommandError, match="either a plain list"):
        select_fields("author,-diff", _DEFAULT, _CATALOGUE)


def test_an_unknown_name_names_the_known_ones():
    """A typo that quietly emitted nothing is the failure worth
    preventing, so the message has to carry the catalogue."""
    with pytest.raises(CommandError, match="authr.*change_id, author"):
        select_fields("authr", _DEFAULT, _CATALOGUE)


def test_an_attribute_value_reads_as_dot_not_as_python():
    assert dot_attribute(True) == "true"
    assert dot_attribute(False) == "false"
    assert dot_attribute(["main", "dev"]) == "main dev"
    assert dot_attribute(None) == ""


def _remote(name: str, *, tracked: bool = True, synced: bool = True) -> dict:
    return {"remote": name, "tracked": tracked, "synced": synced,
            "ahead": 0, "behind": 0}


def test_a_bookmark_with_no_remote_at_all_needs_pushing():
    assert unpushed({}, "fix/x") is True
    assert unpushed({"fix/x": [_remote("git")]}, "fix/x") is True


def test_a_synced_tracked_remote_means_nothing_to_push():
    assert unpushed({"fix/x": [_remote("git"), _remote("origin")]},
                    "fix/x") is False


def test_an_unsynced_tracked_remote_needs_pushing():
    assert unpushed({"fix/x": [_remote("origin", synced=False)]},
                    "fix/x") is True


def test_an_untracked_remote_never_decides_it():
    """kr8s carries `main@lilatomic` 31 commits behind its own `main`.
    jj does not push to an untracked remote, so counting one made a
    synced bookmark read as needing a push."""
    remotes = {"main": [_remote("origin"),
                        _remote("lilatomic", tracked=False, synced=False)]}
    assert unpushed(remotes, "main") is False


def test_an_untracked_remote_alone_still_needs_pushing():
    remotes = {"fix/x": [_remote("lilatomic", tracked=False, synced=False)]}
    assert unpushed(remotes, "fix/x") is True


def test_the_graph_is_one_named_digraph_ending_in_a_newline():
    out = render_dot([("aa", [])], {}, name="op_log")
    graph = pygraphviz.AGraph(string=out)
    assert graph.directed
    assert graph.name == "op_log"
    assert out.endswith("}\n")


def test_cli_log_dot_names_every_commit_and_edge(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [base.id])
    builder.set_description('a "quoted" subject')
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("child")
    workspace.check_out(repo, child)

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", "all()", "--dot"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    nodes, edges = parse_dot(result.stdout)
    assert child.id.hex() in nodes
    assert edges[child.id.hex()] == [(base.id.hex(), "direct")]
    assert 'a "quoted" subject' in _attrs(result.stdout,
                                          child.id.hex())["label"]


def test_cli_log_dot_refuses_flags_that_shape_rows(workspace, repo, settings):
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R",
         str(workspace.workspace_root), "log", "--dot", "--no-graph"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "--dot cannot be used with --no-graph" in result.stderr


def test_cli_op_log_dot_draws_the_operation_graph(workspace, repo, settings):
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R",
         str(workspace.workspace_root), "op", "log", "--dot"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert pygraphviz.AGraph(string=result.stdout).name == "op_log"
    # The operation log is a line, so every row but the oldest points
    # at the one before it.
    _nodes, edges = parse_dot(result.stdout)
    assert edges


def test_cli_evolog_dot_draws_the_evolution_graph(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, commit)
    builder.set_description("rewritten")
    rewritten = builder.write(repo)
    tx.set_wc_commit("default", rewritten.id)
    tx.rebase_descendants()
    tx.commit("rewrite")

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "evolog", "--dot"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert pygraphviz.AGraph(string=result.stdout).name == "evolog"
    assert "rewritten" in result.stdout


def test_cli_log_dot_writes_the_default_fields_as_attributes(
        workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", "@", "--dot"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    attrs = _attrs(result.stdout, commit.id.hex())
    assert attrs["commit_id"] == commit.id.hex()
    assert attrs["change_id"] == commit.change_id.reverse_hex()
    assert attrs["description"]
    # The costly fields stay out until they are named.
    assert "files" not in attrs
    assert "diff" not in attrs


def test_an_empty_field_is_absent_rather_than_empty():
    """DOT treats an attribute set to the empty string as unset, so
    graphviz drops it on the way out. A field with nothing to report
    therefore reads as absent, not as present-and-empty."""
    out = render_dot([("aa", [])], {"aa": "A"},
                     attributes={"aa": {"bookmarks": "", "change_id": "z"}})
    attrs = _attrs(out, "aa")
    assert attrs["change_id"] == "z"
    assert "bookmarks" not in attrs


def test_cli_log_dot_fields_selects_and_adds(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)

    exact = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", "@", "--dot", "--dot-fields", "commit_id"],
        capture_output=True, text=True,
    )
    assert exact.returncode == 0, exact.stderr
    only, _edges = parse_dot(exact.stdout)
    exact_attrs = _attrs(exact.stdout, only[0])
    assert exact_attrs["commit_id"]
    assert "change_id" not in exact_attrs
    assert "description" not in exact_attrs

    added = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", "@", "--dot", "--dot-fields", "+files"],
        capture_output=True, text=True,
    )
    assert added.returncode == 0, added.stderr
    names, _edges = parse_dot(added.stdout)
    added_attrs = _attrs(added.stdout, names[0])
    assert added_attrs["change_id"]
    assert added_attrs["files"] == "a.txt"


def test_cli_log_dot_fields_rejects_a_typo_and_a_stray_flag(
        workspace, repo, settings):
    root = str(workspace.workspace_root)
    typo = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", root, "log", "--dot",
         "--dot-fields", "authr"],
        capture_output=True, text=True,
    )
    assert typo.returncode == 2
    assert "unknown --dot-fields name 'authr'" in typo.stderr
    assert "author" in typo.stderr

    stray = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", root, "log",
         "--dot-fields", "author"],
        capture_output=True, text=True,
    )
    assert stray.returncode == 2
    assert "--dot-fields requires --dot" in stray.stderr


def test_cli_log_dot_reports_a_bookmark_with_no_remote_as_unpushed(
        workspace, repo, settings):
    """The fixture repository has no remote, so every bookmark on it
    would be created by a push."""
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)

    subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "bookmark",
         "create", "topic", "-r", "@"],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log", "-r", "@",
         "--dot", "--dot-fields", "bookmarks,unpushed_bookmarks"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    nodes, _edges = parse_dot(result.stdout)
    attrs = _attrs(result.stdout, nodes[0])
    assert attrs["bookmarks"] == "topic"
    assert attrs["unpushed_bookmarks"] == "topic"


def test_cli_bookmark_list_template_can_name_the_remote_state(
        workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "bookmark",
         "create", "topic", "-r", "@"],
        capture_output=True, text=True, check=True,
    )

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "bookmark",
         "list", "-T", "{{ name }} unpushed={{ unpushed }} "
                       "{{ remotes | tojson }}"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "topic unpushed=True" in result.stdout
    # The listing still renders, whether or not a remote exists.
    assert "[" in result.stdout


def test_cli_log_dot_key_change_id_names_nodes_by_change(
        workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")

    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log", "-r", "@",
         "--dot", "--dot-key", "change_id"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    nodes, _edges = parse_dot(result.stdout)
    assert nodes == [commit.change_id.reverse_hex()]


def test_cli_log_dot_key_survives_a_rewrite(workspace, repo, settings):
    """A commit id is a content hash, so a rewrite replaces it -- and
    the old one still resolves, to the obsolete predecessor. A graph
    meant to be read back after a rewrite has to be keyed on the change
    id, which is the id that does not move."""
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("one\n")
    repo, _ = workspace.snapshot(settings)
    before = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, before)
    builder.set_description("rewritten")
    rewritten = builder.write(repo)
    tx.set_wc_commit("default", rewritten.id)
    tx.rebase_descendants()
    tx.commit("rewrite")

    assert rewritten.id.hex() != before.id.hex(), "the rewrite moved the commit id"
    assert (rewritten.change_id.reverse_hex()
            == before.change_id.reverse_hex()), "the change id stayed put"

    key = before.change_id.reverse_hex()
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", key, "--no-graph", "-T", "{{ commit_id }}"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert rewritten.id.hex() in result.stdout
    assert before.id.hex() not in result.stdout


def test_cli_log_dot_key_requires_dot(workspace, repo, settings):
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R",
         str(workspace.workspace_root), "log", "--dot-key", "change_id"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "--dot-key requires --dot" in result.stderr


def test_cli_op_log_dot_refuses_the_op_diff_flag(workspace, repo, settings):
    """A node label holding a whole operation diff is not a label."""
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R",
         str(workspace.workspace_root), "op", "log", "--dot", "--op-diff"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "--dot cannot be used with --op-diff" in result.stderr
