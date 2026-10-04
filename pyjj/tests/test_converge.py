"""Tests for the `jj_lib::converge` bindings: find_divergent_changes,
TruncatedEvolutionGraph.converge, Transaction.apply_converge_solution.

Uses real `pyjj.UserSettings()` rather than the usual `load_config=False`
`settings` fixture, since the search space (`mutable() & divergent()`,
jj's own `revsets.converge` default) is built from bundled
`revsets.toml` aliases -- same constraint as test_absorb.py.

Divergence is built in-process (`duplicate()` + `set_change_id()`),
which yields two visible commits sharing one change id without walking
the operation log -- the same recipe
test_id_prefix.py's divergent-change test uses.
"""

from pathlib import Path

import pytest

import pyjj

SEARCH = "mutable() & divergent()"


def _setup(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))
    return settings, ws, repo


def _commit_with_file(repo, settings, ws, parent_id, name, content, message):
    """A commit holding one file, becoming the new working-copy commit."""
    tx = repo.start_transaction(settings)
    child = tx.new_commit(settings, [parent_id]).write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit(f"new {name}")
    ws.check_out(repo, child)
    Path(ws.workspace_root, name).write_text(content)
    repo, _ = ws.snapshot(settings)
    tx = repo.start_transaction(settings)
    head = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    tx.rewrite_commit(settings, head).set_description(message).write(repo)
    tx.rebase_descendants()
    return tx.commit(f"describe {name}")


def _twin(repo, settings, source, description=None):
    """A second visible commit sharing `source`'s change id."""
    tx = repo.start_transaction(settings)
    (dup,) = tx.duplicate([source])
    builder = tx.rewrite_commit(settings, dup)
    builder.set_change_id(source.change_id)
    if description is not None:
        builder.set_description(description)
    builder.write(repo)
    tx.rebase_descendants()
    return tx.commit("create divergent twin")


def test_no_divergence_finds_nothing(tmp_path):
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                      "a.txt", "a\n", "one")
    assert repo.find_divergent_changes(settings, SEARCH) == []


def test_finds_one_group_of_two(tmp_path):
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "original")
    original = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    repo = _twin(repo, settings, original)

    found = repo.find_divergent_changes(settings, SEARCH)
    assert len(found) == 1
    assert found[0].change_id.hex() == original.change_id.hex()
    hexes = {c.id.hex() for c in found[0].commits}
    assert len(hexes) == 2 and original.id.hex() in hexes


def test_identical_twins_solve_everything(tmp_path):
    """Same author, description, parents and tree: every attribute
    solves on the heuristics alone, and the tree is ready immediately
    (parents solved means the tree is computable in the first pass)."""
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "original")
    original = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    repo = _twin(repo, settings, original)

    (group,) = repo.find_divergent_changes(settings, SEARCH)
    graph = pyjj.TruncatedEvolutionGraph(repo, group.commits)
    assert graph.change_id.hex() == original.change_id.hex()
    assert {c.hex() for c in graph.divergent_commit_ids} == {
        c.id.hex() for c in group.commits}

    result = graph.converge()
    assert result.author.solved
    assert result.author.value.name == original.author.name
    assert result.description.solved
    assert result.description.value == "original"
    assert result.parents.solved
    assert [p.hex() for p in result.parents.value] == [
        p.hex() for p in original.parent_ids]
    assert result.tree is not None


def test_apply_writes_the_solution_and_rebases_children(tmp_path):
    """The solution keeps the change id, supersedes both twins, and the
    twins' child is rebased onto it -- `apply_solution`'s contract, the
    same one `jj converge` relies on for bookmark following."""
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "original")
    original = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    # A child on the original, so the apply has something to rebase.
    tx = repo.start_transaction(settings)
    child = tx.new_commit(settings, [original.id]).write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("new child")
    repo = _twin(repo, settings, original)

    (group,) = repo.find_divergent_changes(settings, SEARCH)
    result = pyjj.TruncatedEvolutionGraph(repo, group.commits).converge()
    assert result.tree is not None

    tx = repo.start_transaction(settings)
    solution, num_rebased = tx.apply_converge_solution(
        result.author.value, result.description.value,
        result.parents.value, result.tree, group.change_id,
        [c.id for c in group.commits])
    tx.rebase_descendants()
    repo = tx.commit("converge twins")

    assert solution.change_id.hex() == original.change_id.hex()
    assert num_rebased == 1
    assert repo.find_divergent_changes(settings, SEARCH) == []
    rebased_child = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    assert rebased_child.parent_ids[0].hex() == solution.id.hex()
    assert rebased_child.read_file("a.txt") == b"a\n"


def test_three_way_description_split_is_unsolved(tmp_path):
    """Three distinct descriptions cannot merge trivially: the
    description comes back unsolved, carrying the base commit to merge
    from. Author and parents still solve, so the tree is ready -- only
    the description blocks the apply."""
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "v1")
    v1 = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    repo = _twin(repo, settings, v1, description="v2\n")
    repo = _twin(repo, settings, v1, description="v3\n")

    (group,) = repo.find_divergent_changes(settings, SEARCH)
    assert len(group.commits) == 3
    result = pyjj.TruncatedEvolutionGraph(repo, group.commits).converge()
    assert result.author.solved
    assert result.parents.solved
    assert result.tree is not None
    description = result.description
    assert not description.solved
    assert description.value is None
    assert description.base_commit is not None
    assert description.excluded == []


def test_distinct_parents_are_unsolved_but_overridable(tmp_path):
    """Twins on different parents cannot agree on parents: unsolved,
    with the descendant-side twin excluded -- and no tree yet, since
    the tree needs settled parents. Passing the parents explicitly
    (what the CLI's second pass does once it knows them) computes it."""
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "original")
    original = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    # Second head on the root: a different parent for the twin.
    root = repo.revset(settings, "root()")[0]
    tx = repo.start_transaction(settings)
    side_head = tx.new_commit(settings, [root.id]).write(repo)
    tx.rebase_descendants()
    repo = tx.commit("side head")
    tx = repo.start_transaction(settings)
    tx.rewrite_commit(settings, repo.get_commit(side_head.id)).set_description("side").write(repo)
    tx.rebase_descendants()
    repo = tx.commit("describe side")
    side = repo.revset(settings, "description(side)")[0]

    tx = repo.start_transaction(settings)
    (dup,) = tx.duplicate([original])
    builder = tx.rewrite_commit(settings, dup)
    builder.set_change_id(original.change_id)
    builder.set_parents([side.id])
    builder.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("twin on other parent")

    (group,) = repo.find_divergent_changes(settings, SEARCH)
    graph = pyjj.TruncatedEvolutionGraph(repo, group.commits)
    result = graph.converge()
    assert not result.parents.solved
    assert result.parents.value is None
    assert result.tree is None

    explicit = graph.converge(parents=[p for p in original.parent_ids])
    assert explicit.parents.solved
    assert explicit.tree is not None


def test_graph_needs_multiple_commits_for_one_change(tmp_path):
    """The graph constructor enforces `jj_lib`'s own preconditions: more
    than one commit, all sharing a change id."""
    settings, ws, repo = _setup(tmp_path)
    wc = repo.view()["default"]
    repo = _commit_with_file(repo, settings, ws, pyjj.CommitId(wc),
                             "a.txt", "a\n", "original")
    original = repo.get_commit(pyjj.CommitId(repo.view()["default"]))
    with pytest.raises(pyjj.JjError, match="multiple divergent commits"):
        pyjj.TruncatedEvolutionGraph(repo, [original])

    repo = _twin(repo, settings, original)
    twin = next(c for c in repo.revset(settings, "all()")
                if c.id.hex() != original.id.hex()
                and c.change_id.hex() == original.change_id.hex())
    other = repo.revset(settings, "root()")[0]
    with pytest.raises(pyjj.JjError, match="same change-id"):
        pyjj.TruncatedEvolutionGraph(repo, [original, other])
