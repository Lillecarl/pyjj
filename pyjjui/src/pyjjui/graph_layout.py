"""Pure-Python lane/column layout for `list[GraphNode]` -- the DAG-drawing
piece jjui gets for free from `jj log`'s own ASCII art (parsed out of a
subprocess); pyjjui computes it directly from `log_graph()`'s structured
data instead. Standard technique (same idea git/lazygit/tig graphs use):
walk nodes in the topological order `log_graph()` already provides
(descendants before ancestors), tracking one "lane" per in-flight edge.
"""

from dataclasses import dataclass

import pyjj


@dataclass(frozen=True)
class LaneEdge:
    """A line segment drawn in this row, from `from_column` to `to_column`
    (equal for a straight pass-through), carrying the edge type of the
    connection it represents (`"direct"`/`"indirect"`/`"missing"`, or
    `"pass"` for an unrelated lane just passing through this row).
    """

    from_column: int
    to_column: int
    edge_type: str


@dataclass(frozen=True)
class GraphRow:
    node: pyjj.GraphNode
    column: int
    """Column this row's own commit glyph is drawn in."""
    edges: list[LaneEdge]
    """Every line segment drawn through or from this row, across all lanes."""
    width: int
    """Number of lanes visible in this row, for allocating render width."""


def layout(nodes: list[pyjj.GraphNode]) -> list[GraphRow]:
    lanes: list[pyjj.CommitId | None] = []
    rows: list[GraphRow] = []

    for node in nodes:
        column = _find_or_allocate(lanes, node.commit.id)

        edges: list[LaneEdge] = [
            LaneEdge(i, i, "pass")
            for i, target in enumerate(lanes)
            if i != column and target is not None
        ]

        if not node.edges:
            lanes[column] = None
        else:
            first, *rest = node.edges
            lanes[column] = first.target
            edges.append(LaneEdge(column, column, first.edge_type))
            for edge in rest:
                target_column = _find_or_allocate(lanes, edge.target)
                lanes[target_column] = edge.target
                edges.append(LaneEdge(column, target_column, edge.edge_type))

        width = max((i for i, t in enumerate(lanes) if t is not None), default=-1) + 1
        rows.append(GraphRow(node=node, column=column, edges=edges, width=max(width, column + 1)))

    return rows


def _find_or_allocate(lanes: list[pyjj.CommitId | None], commit_id: pyjj.CommitId) -> int:
    for i, target in enumerate(lanes):
        if target == commit_id:
            return i
    for i, target in enumerate(lanes):
        if target is None:
            return i
    lanes.append(commit_id)
    return len(lanes) - 1
