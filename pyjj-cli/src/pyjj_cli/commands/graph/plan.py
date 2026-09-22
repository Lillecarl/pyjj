"""graph subcommand: plan — what it would take to match a DOT graph.

Prints jj commands and runs none of them. The plan is the artifact: an
agent reads it, and a wrong graph shows up as a wrong command instead
of as a rewritten repository.
"""
import json
import sys

import pyjj

from ..common import CommandError, _load
from .resolve import read_graph, resolve


def plan(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        steps, commits = resolve(repo, settings,
                                 read_graph(getattr(args, "file")))
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    described = [
        {
            "node": key,
            "change_id": commits[key].change_id.reverse_hex(),
            "commit_id": commits[key].id.hex(),
            "from": [pid.hex() for pid in commits[key].parent_ids],
            "to": [commits[parent].id.hex() for parent in parents],
            "command": ["rebase", "--revision", key]
                       + [flag for parent in parents for flag in ("-d", parent)],
        }
        for key, parents in steps
    ]

    if getattr(args, "format", "text") == "json":
        print(json.dumps({"steps": described,
                          "unchanged": len(commits) - len(described)},
                         indent=2))
        return 0

    for step in described:
        print("pyjj " + " ".join(step["command"]))
    print(f"# {len(described)} commits reshaped, "
          f"{len(commits) - len(described)} unchanged", file=sys.stderr)
    return 0
