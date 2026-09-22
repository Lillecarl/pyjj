"""What `graph_dot.render_dot` writes, and what `log --dot` prints.

The emitter takes `graph_layout`'s item shape, so these tests build the
items by hand rather than through a repository. The one test that does
drive the CLI is there to prove the labels and the rows line up.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from pyjj.graph_dot import escape, render_dot
from pyjj_cli.commands.common import (
    CommandError,
    dot_attribute,
    select_fields,
    unpushed,
)

_CATALOGUE = ("change_id", "author", "description", "files", "diff")
_DEFAULT = ("change_id", "author", "description")


def test_every_node_id_is_quoted():
    """A commit hex can start with a digit, and `4e2a72e` is not a
    numeral, so an unquoted id is a DOT syntax error."""
    out = render_dot([("4e2a72e", [("3a87969", "direct")])], {})
    assert '  "4e2a72e" [label="4e2a72e"];' in out
    assert '  "4e2a72e" -> "3a87969";' in out


def test_a_label_escapes_backslash_quote_and_newline():
    assert escape('a\\b"c\nd') == 'a\\\\b\\"c\\nd'


def test_a_description_with_quotes_stays_one_label():
    out = render_dot([("aa", [])], {"aa": 'fix "the" bug\nsecond line'})
    assert '"aa" [label="fix \\"the\\" bug\\nsecond line"];' in out


def test_edge_types_get_their_own_styles():
    items = [
        ("aa", [("bb", "direct"), ("cc", "indirect"), ("dd", "missing")]),
        ("bb", []),
        ("cc", []),
        ("dd", []),
    ]
    out = render_dot(items, {})
    assert '"aa" -> "bb";' in out
    assert '"aa" -> "cc" [style=dashed];' in out
    assert '"aa" -> "dd" [style=dotted];' in out


def test_a_target_outside_the_rows_gets_a_placeholder_node():
    """`log -r <subset>` reaches parents it does not draw. Without a
    declaration dot invents a node labelled with the bare hex, which
    reads as a commit that is in the graph."""
    out = render_dot([("aa", [("zz", "missing")])], {"aa": "A"})
    assert '"zz" [label="(not shown)", shape=none];' in out


def test_a_row_keeps_its_own_label_over_the_placeholder():
    out = render_dot([("aa", [("bb", "direct")]), ("bb", [])],
                     {"aa": "A", "bb": "B"})
    assert '"bb" [label="B"];' in out
    assert "(not shown)" not in out


def test_fields_become_node_attributes_beside_the_label():
    out = render_dot([("aa", [])], {"aa": "A"},
                     attributes={"aa": {"change_id": "zzz",
                                        "author": "someone"}})
    assert '  "aa" [label="A",\n' in out
    assert '     change_id="zzz",\n' in out
    assert '     author="someone"];' in out


def test_an_attribute_value_is_escaped_like_a_label():
    out = render_dot([("aa", [])], {"aa": "A"},
                     attributes={"aa": {"diff": 'a "b"\nc'}})
    assert 'diff="a \\"b\\"\\nc"' in out


def test_a_node_with_no_attributes_stays_on_one_line():
    out = render_dot([("aa", [])], {"aa": "A"})
    assert '  "aa" [label="A"];' in out


def test_a_placeholder_node_carries_no_attributes():
    """An edge target outside the rows has no row, so it has no fields
    to report -- only that it exists."""
    out = render_dot([("aa", [("zz", "missing")])], {"aa": "A"},
                     attributes={"aa": {"author": "someone"}})
    assert '"zz" [label="(not shown)", shape=none];' in out


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


def test_the_graph_is_one_digraph_ending_in_a_newline():
    out = render_dot([("aa", [])], {})
    assert out.startswith('digraph "log" {\n')
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
    out = result.stdout
    assert out.startswith('digraph "log" {')
    assert f'"{child.id.hex()}" [label=' in out
    assert f'"{child.id.hex()}" -> "{base.id.hex()}";' in out
    assert 'a \\"quoted\\" subject' in out


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
    assert result.stdout.startswith('digraph "op_log" {')
    # The operation log is a line, so every row but the oldest points
    # at the one before it.
    assert result.stdout.count(" -> ") >= 1


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
    assert result.stdout.startswith('digraph "evolog" {')
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
    assert f'commit_id="{commit.id.hex()}"' in result.stdout
    assert 'author=' in result.stdout
    # The costly fields stay out until they are named.
    assert "files=" not in result.stdout
    assert "diff=" not in result.stdout


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
    assert "commit_id=" in exact.stdout
    assert "author=" not in exact.stdout

    added = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), "log",
         "-r", "@", "--dot", "--dot-fields", "+files"],
        capture_output=True, text=True,
    )
    assert added.returncode == 0, added.stderr
    assert "author=" in added.stdout
    assert 'files="a.txt"' in added.stdout


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
    assert 'bookmarks="topic"' in result.stdout
    assert 'unpushed_bookmarks="topic"' in result.stdout


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
    assert f'"{commit.change_id.reverse_hex()}" [label=' in result.stdout
    assert commit.id.hex() not in result.stdout.split("[label=")[0]


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
