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


def lane_prefixes(row, glyph: str) -> tuple[str, str]:
    """The graph column for a row's first line, and for its body lines.

    jj puts one lane every two characters and leaves two spaces before
    the text, so a single-lane row reads `@  text`, not `@ text`. Both
    strings returned already carry that trailing pair, so the caller
    concatenates and prints.
    """
    # A row can draw into a lane it also retires -- a second child
    # reaching the same ancestor -- and `width` counts only the lanes
    # still open after the row. So the drawing is sized from every
    # column the row actually mentions.
    columns = [row.width, row.column + 1]
    columns += [edge.from_column + 1 for edge in row.edges]
    columns += [edge.to_column + 1 for edge in row.edges]
    width = max(columns)
    cells = [" "] * max(2 * width - 1, 1)
    for edge in row.edges:
        lo, hi = sorted((edge.from_column, edge.to_column))
        if lo == hi:
            cells[2 * lo] = "│"
            continue
        for col in range(2 * lo + 1, 2 * hi):
            cells[col] = "─"
        if edge.from_column == row.column:
            cells[2 * edge.to_column] = (
                "╮" if edge.to_column > edge.from_column else "╭")
        else:
            cells[2 * edge.from_column] = (
                "╯" if edge.from_column > edge.to_column else "╰")

    header = list(cells)
    header[2 * row.column] = glyph
    # A body line continues every lane that is still open below this
    # row. A lane is open when its own column carries anything at all;
    # the horizontal fill between lanes sits on odd columns and never
    # continues downwards.
    body = ["│" if i % 2 == 0 and cell != " " else " "
            for i, cell in enumerate(cells)]
    return "".join(header) + "  ", "".join(body) + "  "


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
