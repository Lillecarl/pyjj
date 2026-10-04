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


class PlanError(ValueError):
    """A graph that cannot become a sequence of rebases."""


_ABANDON_VALUES = {"true": True, "1": True, "false": False, "0": False}


def resolve_plan(
    nodes: Sequence[str],
    edges: Mapping[str, Sequence[tuple[str, str]]],
    current: Mapping[str, Sequence[str]],
) -> list[tuple[str, list[str]]]:
    """`[(key, wanted parents)]` for each node whose parents must move.

    Pure: `current` gives each key's parents as the repository has them
    now, and nothing here touches a repository. `nodes` is the set the
    graph declares; an edge may point outside it, at a commit the graph
    names as a fixed parent rather than describes.

    **Ordered parents before children.** A node is emitted only once
    every in-graph parent it wants is already emitted. Declaration
    order is not enough: a graph that swaps two commits declares them
    in the order it likes, and rebasing the child first puts it on the
    parent's *old* position.

    Raises `PlanError` on a cycle -- including a node that is its own
    parent -- because no order of rebases can produce one, and jj would
    take the first few steps before discovering that.
    """
    wanted = {key: [target for target, _kind in edges.get(key, [])]
              for key in nodes}
    known = set(nodes)

    for key, parents in wanted.items():
        if key in parents:
            raise PlanError(f"node {key} is its own parent")
        seen = set()
        for parent in parents:
            if parent in seen:
                raise PlanError(
                    f"node {key} names parent {parent} twice")
            seen.add(parent)

    # Kahn over the in-graph edges, child depending on parent. A node
    # left over when nothing more can be emitted sits on a cycle.
    remaining = {key: {p for p in parents if p in known}
                 for key, parents in wanted.items()}
    order: list[str] = []
    ready = [key for key in nodes if not remaining[key]]
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child, parents in remaining.items():
            if key in parents:
                parents.discard(key)
                if not parents and child not in order and child not in ready:
                    ready.append(child)

    if len(order) != len(nodes):
        stuck = sorted(set(nodes) - set(order))
        raise PlanError(
            "the graph has a cycle through "
            + ", ".join(stuck[:4]) + ("..." if len(stuck) > 4 else ""))

    steps = []
    for key in order:
        if list(current.get(key, [])) != wanted[key]:
            steps.append((key, wanted[key]))
    return steps


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
    nodes, edges, _abandoned = parse_dot_graph(text)
    return nodes, edges


def parse_dot_graph(
    text: str,
) -> tuple[list[str], dict[str, list[tuple[str, str]]], set[str]]:
    """`parse_dot` plus the nodes marked for abandon: `(nodes, edges,
    abandoned)`.

    A node opts into abandonment with an `abandon="true"` attribute
    (`"1"` also reads as yes, `"false"`/`"0"` as no -- anything else
    is a `DotError`, since silently misreading intent here deletes
    history). Every other attribute (the `bookmarks`/`change_id`/...
    fields `--dot-fields` writes) is ignored: a graph `log --dot`
    wrote must stay a plannable graph.
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
    abandoned = set()
    for node in graph.nodes():
        key = str(node)
        if key not in nodes:
            continue
        raw = (node.attr.get("abandon") or "").strip().lower()
        if not raw:
            continue
        if raw not in _ABANDON_VALUES:
            raise DotError(
                f"node {key!r}: abandon must be \"true\" or \"false\", "
                f"not {raw!r}")
        if _ABANDON_VALUES[raw]:
            abandoned.add(key)
    return nodes, edges, abandoned


def resolve_abandons(
    nodes: Sequence[str],
    edges: Mapping[str, Sequence[tuple[str, str]]],
    current: Mapping[str, Sequence[str]],
    abandoned: set[str],
) -> tuple[list[str], dict[str, list[tuple[str, str]]], list[str]]:
    """Fold abandoned nodes out of a target graph: `(nodes, edges,
    abandons)`.

    Pure, like `resolve_plan`: `current` gives each node's parents as
    the repository has them now (keys where the graph names the
    commit, hexes where it only points outside it). The abandoned
    nodes leave the graph, and every edge that pointed at one is
    re-pointed at its current parents instead -- the abandonment half
    of `MutableRepo::new_parents` (an abandoned id becomes its own
    parents, recursively), computed statically here rather than
    mid-transaction the way `pyjjui`'s arrange port does it
    dynamically. A node left pointing at nothing keeps no edge, and a
    node whose edges all resolve away keeps none either.

    The usual refusals still apply, on the resolved graph: abandoning
    a commit the graph merely points at rewrites history outside the
    declared set, and the closure itself must terminate (two nodes
    abandoned onto each other resolve forever).

    `abandons` comes back in declaration order. Execution runs them
    before any rebase: with every abandoned reference already
    re-pointed, the mapping is complete before the first rewrite,
    which is what makes one transaction enough.
    """
    known = set(nodes)
    for key in sorted(abandoned):
        if key not in known:
            raise PlanError(
                f"node {key!r} is marked abandoned but the graph only "
                "points at it -- abandoning it would rewrite history "
                "outside the declared set")
        if not current.get(key):
            raise PlanError(f"node {key!r} cannot be abandoned: it has "
                            "no parents, so it is the root commit")

    def resolve_target(target: str, visiting: frozenset[str]) -> list[str]:
        if target not in abandoned:
            return [target]
        if target in visiting:
            raise PlanError(
                "abandoned nodes point at each other through "
                + ", ".join(sorted(visiting | {target})))
        return [resolved
                for parent in current.get(target, [])
                for resolved in resolve_target(parent, visiting | {target})]

    resolved: dict[str, list[tuple[str, str]]] = {}
    for key in nodes:
        if key in abandoned:
            continue
        parents: list[tuple[str, str]] = []
        for target, kind in edges.get(key, []):
            parents.extend((resolved_target, kind)
                           for resolved_target in resolve_target(target, frozenset()))
        resolved[key] = parents
    kept = [key for key in nodes if key not in abandoned]
    ordered = [key for key in nodes if key in abandoned]
    return kept, resolved, ordered
