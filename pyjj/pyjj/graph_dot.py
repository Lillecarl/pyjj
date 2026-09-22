"""The same DAG `graph_layout` draws in lanes, written as Graphviz DOT.

`layout_keyed` takes `[(key, [(parent_key, edge_type), ...])]` in
topological order, and every caller that draws a graph -- `log`,
`op log`, `evolog`, `op diff` -- already builds that shape to feed
`GraphRenderer`. This emitter takes the same shape, so it reaches all
of them without a second walk of the DAG.

A template (`-T`) cannot produce this. A template sees
`commit.parent_ids`, which is the real parent list; the graph's edges
are what is left after the revset filters, so only `log_graph()` knows
that an edge is `indirect` (the parent was elided) or `missing` (the
parent is outside the revset entirely).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

EdgeType = Literal["direct", "indirect", "missing"]

# jj draws an elided run of commits as a broken line and an ancestor it
# cannot reach as a fainter one. Dashed and dotted are dot's nearest
# equivalents, and they survive every renderer dot has.
_EDGE_ATTRS: dict[str, str] = {
    "direct": "",
    "indirect": " [style=dashed]",
    "missing": " [style=dotted]",
}

_HEADER = (
    "  rankdir=TB;\n"
    '  node [shape=box, style=rounded, fontname="monospace"];\n'
)


def escape(text: str) -> str:
    """One label, as a DOT quoted string's contents.

    The backslash goes first: it is what makes a following `\\"` or
    `\\n` mean the character and not dot's own escape.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def quote(text: str) -> str:
    return f'"{escape(text)}"'


def render_dot(
    items: Sequence[tuple[str, Sequence[tuple[str, EdgeType]]]],
    labels: Mapping[str, str],
    *,
    name: str = "log",
) -> str:
    """The graph as one `digraph`, ending in a newline.

    `items` is the topological row list; `labels` gives each key its
    node label, defaulting to the key. An edge target that is not a row
    of its own gets a placeholder node -- jj's `~` -- so a truncated
    history reads as "this parent exists and is not shown" rather than
    as a node dot invented from a bare hex id.
    """
    rows = {key for key, _ in items}
    lines = [f"digraph {quote(name)} {{", _HEADER.rstrip("\n")]

    for key, _parents in items:
        lines.append(f"  {quote(key)} [label={quote(labels.get(key, key))}];")

    outside: list[str] = []
    for _key, parents in items:
        for target, _edge_type in parents:
            if target not in rows and target not in outside:
                outside.append(target)
    for target in outside:
        lines.append(f'  {quote(target)} [label="(not shown)", shape=none];')

    for key, parents in items:
        for target, edge_type in parents:
            attrs = _EDGE_ATTRS.get(edge_type, "")
            lines.append(f"  {quote(key)} -> {quote(target)}{attrs};")

    lines.append("}")
    return "\n".join(lines) + "\n"
