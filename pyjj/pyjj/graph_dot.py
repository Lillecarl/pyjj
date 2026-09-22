"""The same DAG `graph_layout` draws in lanes, written as Graphviz DOT.

`layout_keyed` takes `[(key, [(parent_key, edge_type), ...])]` in
topological order, and every caller that draws a graph -- `log`,
`op log`, `evolog`, `op diff` -- already builds that shape to feed
`GraphRenderer`. This module reads and writes the same shape, so it
reaches all of them without a second walk of the DAG.

A template (`-T`) cannot produce this. A template sees
`commit.parent_ids`, which is the real parent list; the graph's edges
are what is left after the revset filters, so only `log_graph()` knows
that an edge is `indirect` (the parent was elided) or `missing` (the
parent is outside the revset entirely).

Both directions go through `pygraphviz`, which binds libcgraph -- the
same parser and writer `dot` itself uses. Hand-written DOT is where
this gets silently wrong: an `a -> b -> c` chain is two edges, ids need
not be quoted, comments and subgraphs are legal, and a label carrying
a quote or a backslash has to survive a round trip. A regex reading
line by line misses every one of those.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pygraphviz

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

EdgeType = Literal["direct", "indirect", "missing"]

# jj draws an elided run of commits as a broken line and an ancestor it
# cannot reach as a fainter one. Dashed and dotted are dot's nearest
# equivalents, and they survive every renderer dot has.
_EDGE_STYLE: dict[str, str] = {"indirect": "dashed", "missing": "dotted"}
_EDGE_TYPE: dict[str, str] = {"dashed": "indirect", "dotted": "missing"}

_NOT_SHOWN = "(not shown)"


class DotError(ValueError):
    """A graph this module cannot read, or cannot read unambiguously."""


def render_dot(
    items: Sequence[tuple[str, Sequence[tuple[str, EdgeType]]]],
    labels: Mapping[str, str],
    *,
    name: str = "log",
    attributes: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """The graph as one `digraph`, ending in a newline.

    `items` is the topological row list; `labels` gives each key its
    node label, defaulting to the key. An edge target that is not a row
    of its own gets a placeholder node -- jj's `~` -- so a truncated
    history reads as "this parent exists and is not shown" rather than
    as a node dot invented from a bare id.

    `attributes` gives a key's fields as DOT node attributes, so a
    reader gets them as a dict instead of re-splitting the label.
    """
    # strict=False: a strict digraph silently collapses a repeated
    # edge, and two edges between the same pair are a real shape here.
    graph = pygraphviz.AGraph(directed=True, strict=False, name=name)
    graph.graph_attr["rankdir"] = "TB"
    graph.node_attr.update(shape="box", style="rounded", fontname="monospace")

    rows = {key for key, _ in items}
    for key, _parents in items:
        graph.add_node(key, label=labels.get(key, key),
                       **dict((attributes or {}).get(key, {})))

    outside: list[str] = []
    for _key, parents in items:
        for target, _edge_type in parents:
            if target not in rows and target not in outside:
                outside.append(target)
    for target in outside:
        graph.add_node(target, label=_NOT_SHOWN, shape="none")

    for key, parents in items:
        for target, edge_type in parents:
            style = _EDGE_STYLE.get(edge_type)
            graph.add_edge(key, target, **({"style": style} if style else {}))

    text = graph.to_string()
    return text if text.endswith("\n") else text + "\n"


def parse_dot(text: str) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """A graph's nodes and edges, as `(nodes, {key: [(target, type)]})`.

    Node order is the order the graph declares them, which is the
    topological order `render_dot` writes and an editor would keep.
    Edge order per node is likewise the declared order, because a
    merge's first parent is not interchangeable with its second.

    The placeholder nodes `render_dot` writes for ancestors outside the
    graph are dropped: they name a commit the graph is not describing.
    """
    try:
        graph = pygraphviz.AGraph(string=text)
    except Exception as e:  # pygraphviz raises bare exceptions on a bad parse
        raise DotError(str(e).strip() or "cannot parse as DOT") from e
    if not graph.directed:
        raise DotError("the graph is not directed, so it names no parents")

    nodes = [str(node) for node in graph.nodes()
             if node.attr["label"] != _NOT_SHOWN]
    edges: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges():
        source, target = str(edge[0]), str(edge[1])
        edges.setdefault(source, []).append(
            (target, _EDGE_TYPE.get(edge.attr["style"] or "", "direct")))
    return nodes, edges
