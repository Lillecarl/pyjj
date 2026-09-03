"""operation subcommand: evolog — how a change evolved across rewrites."""
import sys

import pyjj

from ..common import CommandError, _load, _resolve_all


def evolog(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        revisions = getattr(args, "revisions", None) or ["@"]
        if isinstance(revisions, str):
            revisions = [revisions]
        commits = _resolve_all(repo, settings, revisions)
        if not commits:
            print("No revisions to show")
            return 0

        limit = getattr(args, "limit", None)
        if limit == 0:
            limit = None
        entries = repo.evolution_log([c.id for c in commits], limit=limit)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    for entry in entries:
        commit = entry.commit
        description = (
            commit.description.splitlines()[0]
            if commit.description
            else "(no description set)"
        )
        change = commit.change_id.reverse_hex()[:8]
        print(f"{change} {commit.id.hex()[:8]} {description}")
        if entry.operation is not None:
            # Same shape as `jj evolog`'s second line: short op id plus
            # the operation's own description.
            op = entry.operation
            print(f"│ -- operation {op.id[:12]} {op.description}".rstrip())
    return 0
