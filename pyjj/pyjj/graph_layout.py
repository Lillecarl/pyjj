"""Shared lane/column layout for `list[GraphNode]` — the DAG-drawing
piece jjui gets for free from `jj log`'s own ASCII art.

Moved here from pyjjui so both pyjjui and pyjj-cli can reuse it
without depending on each other. Pure Python, no Textual, no
argcomplete — only `pyjj.GraphNode`/`pyjj.CommitId`.

Walk nodes in the topological order `log_graph()` already provides
(descendants before ancestors), tracking one "lane" per in-flight edge.
"""

from dataclasses import dataclass

import pyjj_bindings as _bindings  # avoid circular `import pyjj` at module load

# Re-export types for typing without importing pyjj at runtime
GraphNode = _bindings.GraphNode
CommitId = _bindings.CommitId


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
    node: GraphNode
    column: int
    """Column this row's own commit glyph is drawn in."""
    edges: list[LaneEdge]
    """Every line segment drawn through or from this row, across all lanes."""
    width: int
    """Number of lanes visible in this row, for allocating render width."""


def layout(nodes: list[GraphNode]) -> list[GraphRow]:
    # Each lane holds the (commit_id, edge_type) it's waiting to reach, or
    # None if idle. Tracking edge_type here (not just the id) is what lets a
    # second/third child converging on the same ancestor draw its own
    # correctly-typed merge line into that ancestor's row, instead of the
    # type getting lost the moment the lane was first opened.
    lanes: list[tuple[CommitId, str] | None] = []
    rows: list[GraphRow] = []

    for node in nodes:
        matches = [i for i, lane in enumerate(lanes) if lane is not None and lane[0] == node.commit.id]
        if matches:
            column, converging = matches[0], matches[1:]
        else:
            column, converging = _allocate_lane(lanes), []

        edges: list[LaneEdge] = []
        for i, lane in enumerate(lanes):
            if lane is None or i == column:
                continue
            if i in converging:
                # A second child reaching the same ancestor `node` -- draw
                # its line merging into `column` here and retire the lane,
                # rather than letting it run on as a disconnected vertical
                # bar forever (the bug: forks never visually reconnected).
                edges.append(LaneEdge(i, column, lane[1]))
                lanes[i] = None
            else:
                edges.append(LaneEdge(i, i, "pass"))

        if not node.edges:
            lanes[column] = None
        else:
            first, *rest = node.edges
            lanes[column] = (first.target, first.edge_type)
            edges.append(LaneEdge(column, column, first.edge_type))
            for edge in rest:
                target_column = _find_or_allocate(lanes, edge.target)
                lanes[target_column] = (edge.target, edge.edge_type)
                edges.append(LaneEdge(column, target_column, edge.edge_type))

        width = max((i for i, lane in enumerate(lanes) if lane is not None), default=-1) + 1
        rows.append(GraphRow(node=node, column=column, edges=edges, width=max(width, column + 1)))

    return rows


def _allocate_lane(lanes: list[tuple[CommitId, str] | None]) -> int:
    for i, lane in enumerate(lanes):
        if lane is None:
            return i
    lanes.append(None)
    return len(lanes) - 1


def _find_or_allocate(
    lanes: list[tuple[CommitId, str] | None], commit_id: CommitId
) -> int:
    for i, lane in enumerate(lanes):
        if lane is not None and lane[0] == commit_id:
            return i
    return _allocate_lane(lanes)
