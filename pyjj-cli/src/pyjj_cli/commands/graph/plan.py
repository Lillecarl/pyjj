"""graph subcommand: plan — what it would take to match a DOT graph.

Reads nothing but topology. A DOT graph carries nodes and edges, so it
can say which commit sits on which parents and nothing about the trees
that result. Conflicts are an outcome of the reshape, never an input,
and a node with no commit behind it is an error rather than a commit to
invent.

Prints jj commands and runs none of them. The plan is the artifact: an
agent reads it, and a wrong graph shows up as a wrong command instead
of as a rewritten repository.
"""
import json
import sys

import pyjj
from pyjj.graph_dot import DotError, parse_dot

from ..common import CommandError, _load


def _resolve(repo, settings, key: str):
    """The commit a node names, by change id or commit id.

    A divergent change names several commits, and jj refuses to resolve
    one -- so this reports it rather than picking. That is the case a
    graph keyed on change ids cannot express at all.
    """
    try:
        return repo.resolve_single(settings, key)
    except pyjj.JjError as e:
        message = getattr(e, "message", str(e))
        raise CommandError(f"node {key!r}: {message}") from e


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as e:
        raise CommandError(f"cannot read {path}: {e.strerror}") from e


def plan(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        nodes, edges = parse_dot(_read(getattr(args, "file")))
    except (DotError, CommandError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not nodes:
        print("Error: the graph declares no nodes", file=sys.stderr)
        return 2

    try:
        commits = {key: _resolve(repo, settings, key) for key in nodes}
        # An edge may point at a commit the graph does not declare --
        # `main`, or an elided ancestor. It still has to exist.
        for parents in edges.values():
            for target, _kind in parents:
                if target not in commits:
                    commits[target] = _resolve(repo, settings, target)
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    steps = []
    for key in nodes:
        commit = commits[key]
        wanted = [commits[target].id.hex()
                  for target, _kind in edges.get(key, [])]
        current = [pid.hex() for pid in commit.parent_ids]
        if wanted == current:
            continue
        if not wanted:
            # A declared node with no out-edge would mean "no parents",
            # which only the root commit has. Far more likely the graph
            # just stops there, so say so instead of rewriting anything.
            raise_on = (f"node {key!r} has no parent edge. A commit with no "
                        "parents is the root commit; add an edge, or leave "
                        "the node out of the graph")
            print(f"Error: {raise_on}", file=sys.stderr)
            return 2
        steps.append({
            "change_id": commit.change_id.reverse_hex(),
            "commit_id": commit.id.hex(),
            "node": key,
            "from": current,
            "to": wanted,
            "command": ["rebase", "--revision", commit.change_id.reverse_hex()]
                       + [flag for target, _kind in edges.get(key, [])
                          for flag in ("-d", target)],
        })

    if getattr(args, "format", "text") == "json":
        print(json.dumps({"steps": steps,
                          "unchanged": len(nodes) - len(steps)}, indent=2))
        return 0

    for step in steps:
        print("pyjj " + " ".join(step["command"]))
    print(f"# {len(steps)} commits reshaped, "
          f"{len(nodes) - len(steps)} unchanged", file=sys.stderr)
    return 0
