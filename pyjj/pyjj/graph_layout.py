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


@dataclass(frozen=True)
class LaneRow:
    """A row's drawing, without the thing being drawn."""

    column: int
    edges: list[LaneEdge]
    width: int


def layout_keyed(items) -> list[LaneRow]:
    """Lane layout for any DAG, not only a commit graph.

    `items` is a sequence of `(key, [(parent_key, edge_type), ...])` in
    topological order, descendants first. Keys only have to compare
    equal; the operation log passes hex strings where `log` passes
    `CommitId`s.
    """
    # Each lane holds the (key, edge_type) it's waiting to reach, or
    # None if idle. Tracking edge_type here (not just the key) is what
    # lets a second/third child converging on the same ancestor draw its
    # own correctly-typed merge line into that ancestor's row, instead
    # of the type getting lost the moment the lane was first opened.
    lanes: list[tuple[object, str] | None] = []
    rows: list[LaneRow] = []

    for key, parents in items:
        matches = [i for i, lane in enumerate(lanes) if lane is not None and lane[0] == key]
        if matches:
            column, converging = matches[0], matches[1:]
        else:
            column, converging = _allocate_lane(lanes), []

        edges: list[LaneEdge] = []
        for i, lane in enumerate(lanes):
            if lane is None or i == column:
                continue
            if i in converging:
                # A second child reaching the same ancestor -- draw its
                # line merging into `column` here and retire the lane,
                # rather than letting it run on as a disconnected
                # vertical bar forever (the bug: forks never visually
                # reconnected).
                edges.append(LaneEdge(i, column, lane[1]))
                lanes[i] = None
            else:
                edges.append(LaneEdge(i, i, "pass"))

        if not parents:
            lanes[column] = None
        else:
            (first_key, first_type), *rest = parents
            lanes[column] = (first_key, first_type)
            edges.append(LaneEdge(column, column, first_type))
            for target, edge_type in rest:
                target_column = _find_or_allocate(lanes, target)
                lanes[target_column] = (target, edge_type)
                edges.append(LaneEdge(column, target_column, edge_type))

        width = max((i for i, lane in enumerate(lanes) if lane is not None), default=-1) + 1
        rows.append(LaneRow(column=column, edges=edges, width=max(width, column + 1)))

    return rows


def layout(nodes: list[GraphNode]) -> list[GraphRow]:
    items = [
        (node.commit.id, [(edge.target, edge.edge_type) for edge in node.edges])
        for node in nodes
    ]
    return [
        GraphRow(node=node, column=row.column, edges=row.edges, width=row.width)
        for node, row in zip(nodes, layout_keyed(items))
    ]


def reverse_graph(items):
    """The same DAG walked the other way.

    Each node's parents become its children and the order flips, which
    is what `jj log --reversed` does (`jj_lib::graph::reverse_graph`).
    Reversing the drawn rows instead would leave a merge's fork
    pointing the wrong way.
    """
    children: dict = {}
    for key, parents in items:
        for target, edge_type in parents:
            children.setdefault(target, []).append((key, edge_type))
    return [(key, children.get(key, [])) for key, _ in reversed(items)]


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
