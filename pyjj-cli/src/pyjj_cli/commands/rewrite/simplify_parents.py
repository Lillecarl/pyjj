"""rewrite command: simplify-parents — drop redundant parent edges."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import _check_rewritable, _finish, _resolve_all, command, write_tx

if TYPE_CHECKING:
    import argparse

    import pyjj


@command
def simplify_parents(args: argparse.Namespace) -> int:
    """`jj simplify-parents`: remove parents reachable through another parent.

    Where a revision has both B and C as parents and C is already an
    ancestor of B, the edge to C says nothing the edge to B does not.
    Dropping it changes no revision's content, only the shape of the
    graph.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        sources = list(getattr(args, "sources", None) or [])
        revisions = list(getattr(args, "revisions", None) or [])
        if sources:
            revisions += [f"descendants({source})" for source in sources]
        if not revisions:
            # jj falls back to `revsets.simplify-parents`, then to this.
            revisions = ["reachable(@, mutable())"]

        targets = _resolve_all(repo, settings, revisions)
        # jj checks the whole target set, not only the commits that turn
        # out to have a redundant edge.
        _check_rewritable(tx, settings, targets)
        simplified = 0
        for commit in targets:
            keep = _essential_parents(repo, settings, commit)
            if keep is None:
                continue
            builder = tx.rewrite_commit(settings, commit)
            builder.set_parents(keep)
            builder.write(repo)
            simplified += 1

        if not simplified:
            print("Nothing changed.", file=sys.stderr)
            return 0
        _finish(tx, f"simplify {simplified} commits", settings, ws, repo, trial=args)
        print(f"Removed parent edges from {simplified} commits")
        return 0


def _essential_parents(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, commit: pyjj.Commit):
    """The parents worth keeping, or `None` when none can be dropped."""
    parents = list(commit.parent_ids)
    if len(parents) < 2:
        return None
    keep = []
    for parent in parents:
        others = [p.hex() for p in parents if p.hex() != parent.hex()]
        # `p & ::(others)` is non-empty exactly when some other parent
        # already reaches this one.
        expression = f"{parent.hex()} & ::({'|'.join(others)})"
        if not repo.revset(settings, expression):
            keep.append(parent)
    return None if len(keep) == len(parents) else keep
