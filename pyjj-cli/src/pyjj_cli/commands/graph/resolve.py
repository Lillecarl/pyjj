"""What `graph plan` and `graph apply` share: a graph, resolved.

Reads nothing but topology. A DOT graph carries nodes and edges, so it
can say which commit sits on which parents and nothing about the trees
that result. Conflicts are an outcome of the reshape, never an input,
and a node with no commit behind it is an error rather than a commit to
invent.
"""
import sys

import pyjj
from pyjj.graph_dot import (DotError, PlanError, parse_dot_graph, resolve_abandons,
                            resolve_plan)

from ..common import CommandError


def read_graph(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as e:
        raise CommandError(f"cannot read {path}: {e.strerror}") from e


def resolve_one(repo, settings, key: str):
    """The commit a node names, by change id or commit id.

    A divergent change names several commits and jj refuses to resolve
    one, so this reports that rather than picking. It is the case a
    graph keyed on change ids cannot express at all.
    """
    try:
        return repo.resolve_single(settings, key)
    except pyjj.JjError as e:
        raise CommandError(
            f"node {key!r}: {getattr(e, 'message', e)}") from e


def resolve(repo, settings, text: str):
    """`(steps, abandons, commits)` -- the reshape, and every commit it
    names.

    A step is `(key, [parent keys])` in an order that puts a parent
    before any child that moves onto it. `abandons` are keys in
    declaration order, run before any step: with every abandoned
    reference already re-pointed at the abandoned commit's own
    parents, the mapping is complete before the first rewrite.
    """
    try:
        nodes, edges, abandoned = parse_dot_graph(text)
    except DotError as e:
        raise CommandError(str(e)) from e
    if not nodes:
        raise CommandError("the graph declares no nodes")

    commits = {key: resolve_one(repo, settings, key) for key in nodes}
    # An edge may point at a commit the graph does not describe --
    # `main`, or an ancestor left outside it. It still has to exist.
    # Edges off abandoned nodes are dropped with the node, so they
    # resolve nothing.
    for key in nodes:
        if key in abandoned:
            continue
        for target, _kind in edges.get(key, []):
            if target not in commits:
                commits[target] = resolve_one(repo, settings, target)

    current = {key: [pid.hex() for pid in commits[key].parent_ids]
               for key in nodes}
    # The resolver compares keys, so the repository's parents have to
    # be spelled the way the graph spells them.
    by_hex = {commit.id.hex(): key for key, commit in commits.items()}
    current = {key: [by_hex.get(hexed, hexed) for hexed in parents]
               for key, parents in current.items()}
    try:
        kept, resolved_edges, abandons = resolve_abandons(
            nodes, edges, current, abandoned)
    except PlanError as e:
        raise CommandError(str(e)) from e

    # Grandparent-resolution can surface a parent no edge named -- the
    # parent of an abandoned node nobody else points at. It still has
    # to exist, and later stages address everything through `commits`.
    for key in kept:
        for parent, _kind in resolved_edges.get(key, []):
            if parent not in commits:
                commits[parent] = resolve_one(repo, settings, parent)

    for key in kept:
        if not resolved_edges.get(key) and commits[key].parent_ids:
            raise CommandError(
                f"node {key!r} has no parent edge, but the commit it names "
                "has parents. A commit with none is the root commit; add "
                "an edge, or leave the node out of the graph")
    try:
        steps = resolve_plan(kept, resolved_edges, current)
    except PlanError as e:
        raise CommandError(str(e)) from e
    return steps, abandons, commits
