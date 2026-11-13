"""history subcommand: diff."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _cli_paths,
    _diff_base,
    _print_diff,
    _resolve_one,
    _warn_unmatched_paths,
    _wc_commit,
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command
def diff(args: argparse.Namespace) -> int:
    """`jj diff` — compare file contents between revisions."""
    with read_repo(args) as (settings, ws, repo):
        paths = _cli_paths(ws, getattr(args, "filesets", None))
        # Determine from/to commits
        if getattr(args, "revisions", None) is not None:
            # -r mode: aggregate diff across revset (like jj diff -r B::D = from first parent to last)
            revs = repo.revset(settings, args.revisions)
            if not revs:
                return 0
            # Multiple revs: diff from first's parent to last (simplified)
            target = revs[0]
            base = _diff_base(repo, settings, revs[-1])
        else:
            from_rev = getattr(args, "from_", None)
            to_rev = getattr(args, "to", None)
            if from_rev is not None or to_rev is not None:
                base = _resolve_one(repo, settings, from_rev) if from_rev else _wc_commit(repo, ws)
                target = _resolve_one(repo, settings, to_rev) if to_rev else _wc_commit(repo, ws)
            else:
                # Default -r @
                target = _wc_commit(repo, ws)
                base = _diff_base(repo, settings, target)
        _print_diff(args, ws, settings, base, target, paths or None)
        # jj warns after the diff, not before it.
        _warn_unmatched_paths(ws, paths, [base, target])
        return 0
