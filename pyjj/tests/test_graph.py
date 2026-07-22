"""Tests for ReadonlyRepo.log_graph(): structured jj-log-graph equivalent.

Unlike revset(), each row comes with edges to its relevant ancestors
(direct/indirect/missing -- see graph.rs's docs) instead of being a flat
list, using the same jj_lib::graph::TopoGroupedGraph primitive
cli/src/commands/log.rs itself is built on.
"""

import pyjj


def _describe(repo, settings, commit, description):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, commit)
    builder.set_description(description)
    commit = builder.write(repo)
    tx.set_wc_commit("default", commit.id)
    tx.rebase_descendants()
    return tx.commit(description), commit


def _new_child(repo, settings, workspace, parent, description):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    builder.set_description(description)
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit(description)
    workspace.check_out(repo, child)
    return repo, repo.get_commit(child.id)


def test_linear_history_has_direct_edges(workspace, repo, settings, wc_commit):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, a, "B")

    nodes = repo.log_graph(settings, f"{root.id.hex()}::{b.id.hex()}")
    by_desc = {n.commit.description: n for n in nodes}

    assert [e.edge_type for e in by_desc["B"].edges] == ["direct"]
    assert by_desc["B"].edges[0].target == a.id
    assert [e.edge_type for e in by_desc["A"].edges] == ["direct"]
    assert by_desc["A"].edges[0].target == root.id


def test_topological_order_is_children_before_parents(workspace, repo, settings, wc_commit):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, a, "B")

    nodes = repo.log_graph(settings, f"{root.id.hex()}::{b.id.hex()}")
    descriptions = [n.commit.description for n in nodes]
    assert descriptions.index("B") < descriptions.index("A") < descriptions.index("root")


def test_skipped_ancestor_produces_an_indirect_edge(workspace, repo, settings, wc_commit):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, skipped = _new_child(repo, settings, workspace, a, "skip me")
    repo, b = _new_child(repo, settings, workspace, skipped, "B")

    # Revset includes root/A/B but not "skip me" -- B's edge to its nearest
    # *visible* ancestor (A) should come back indirect, not direct.
    nodes = repo.log_graph(
        settings, f"{b.id.hex()} | {a.id.hex()} | {root.id.hex()}"
    )
    by_desc = {n.commit.description: n for n in nodes}

    assert "skip me" not in by_desc
    b_edges = by_desc["B"].edges
    assert len(b_edges) == 1
    assert b_edges[0].edge_type == "indirect"
    assert b_edges[0].target == a.id


def test_ancestor_outside_revset_domain_produces_a_missing_edge(
    workspace, repo, settings, wc_commit
):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")

    # Only A is in the revset -- its parent (root) is entirely outside the
    # domain, so the edge to it is "missing", not "direct"/"indirect".
    nodes = repo.log_graph(settings, a.id.hex())
    assert len(nodes) == 1
    assert nodes[0].edges[0].edge_type == "missing"
    assert nodes[0].edges[0].target == root.id


def test_merge_commit_has_two_direct_edges(workspace, repo, settings, wc_commit):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, root, "B")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [a.id, b.id])
    builder.set_description("merge")
    merge_commit = builder.write(repo)
    tx.set_wc_commit("default", merge_commit.id)
    tx.rebase_descendants()
    repo = tx.commit("merge")

    nodes = repo.log_graph(
        settings, f"{merge_commit.id.hex()} | {a.id.hex()} | {b.id.hex()}"
    )
    merge_node = next(n for n in nodes if n.commit.description == "merge")
    assert {e.edge_type for e in merge_node.edges} == {"direct"}
    assert {e.target for e in merge_node.edges} == {a.id, b.id}


def test_limit_stops_after_n_rows(workspace, repo, settings, wc_commit):
    repo, root = _describe(repo, settings, wc_commit, "root")
    repo, a = _new_child(repo, settings, workspace, root, "A")
    repo, b = _new_child(repo, settings, workspace, a, "B")

    nodes = repo.log_graph(settings, f"{root.id.hex()}::{b.id.hex()}", limit=2)
    assert len(nodes) == 2
    assert [n.commit.description for n in nodes] == ["B", "A"]
