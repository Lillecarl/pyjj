"""graph subcommand: plan — what it would take to match a DOT graph.

Prints jj commands and runs none of them. The plan is the artifact: an
agent reads it, and a wrong graph shows up as a wrong command instead
of as a rewritten repository.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import CommandError, command, read_repo
from .resolve import read_graph, resolve

if TYPE_CHECKING:
    import argparse


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def plan(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, repo):
        try:
            steps, abandons, commits = resolve(repo, settings,
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
        ] + [
            {
                "node": key,
                "change_id": commits[key].change_id.reverse_hex(),
                "commit_id": commits[key].id.hex(),
                "from": [pid.hex() for pid in commits[key].parent_ids],
                "command": ["abandon", key],
            }
            for key in abandons
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
