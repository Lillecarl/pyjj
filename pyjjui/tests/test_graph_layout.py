"""Tests for graph_layout.layout(): lane/column assignment over log_graph() nodes."""

import pyjj
from pyjjui.graph_layout import layout


def _new_child(repo, settings, workspace, parent, description):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    builder.set_description(description)
    child = builder.write(repo)
    tx.edit(workspace.workspace_name, child)
    tx.rebase_descendants()
    repo = tx.commit(description)
    workspace.check_out(repo, child)
    return repo, repo.get_commit(child.id)


def test_linear_history_stays_in_a_single_lane(workspace, settings):
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "@")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, a, "B")

    nodes = repo.log_graph(settings, f"{root.id.hex()}::{b.id.hex()}")
    rows = layout(nodes)

    assert [row.column for row in rows] == [0, 0, 0]


def test_merge_commit_allocates_a_second_lane(workspace, settings):
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "@")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, root, "B")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [a.id, b.id])
    builder.set_description("merge")
    merge_commit = builder.write(repo)
    tx.edit(workspace.workspace_name, merge_commit)
    tx.rebase_descendants()
    repo = tx.commit("merge")

    nodes = repo.log_graph(
        settings, f"{merge_commit.id.hex()} | {a.id.hex()} | {b.id.hex()}"
    )
    rows = layout(nodes)
    by_desc = {row.node.commit.description: row for row in rows}

    merge_row = by_desc["merge"]
    assert merge_row.column == 0
    # The merge fans out onto two distinct lanes for its two parents.
    assert {edge.to_column for edge in merge_row.edges} == {0, 1}

    # A and B each keep occupying the lane the merge routed them onto.
    assert {by_desc["A"].column, by_desc["B"].column} == {0, 1}


def test_every_row_has_a_valid_column_within_its_width(workspace, settings):
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "@")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, root, "B")
    repo, c = _new_child(repo, settings, workspace, a, "C")

    nodes = repo.log_graph(
        settings,
        f"{root.id.hex()} | {a.id.hex()} | {b.id.hex()} | {c.id.hex()}",
    )
    rows = layout(nodes)
    for row in rows:
        assert 0 <= row.column < row.width
