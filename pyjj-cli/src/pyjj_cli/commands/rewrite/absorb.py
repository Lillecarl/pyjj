"""pyjj-cli rewrite command: absorb."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    _changed_files,
    _finish,
    _ignore_immutable,
    _resolve_one,
    _run_diff_tool,
    _split_changed,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def absorb(args: argparse.Namespace) -> int:
    """`jj absorb --from X --into Y [FILESETS]` — move hunks into ancestors."""
    with write_tx(args) as (settings, ws, repo, tx):
        source = _resolve_one(repo, settings, args.from_)
        dest_expr = getattr(args, "into", None)
        paths = getattr(args, "filesets", None) or None
        selections = None
        tool = getattr(args, "tool", None)
        if tool:
            parent = repo.get_commit(source.parent_ids[0])
            before, after = _split_changed(
                _changed_files(repo, settings, parent, source))
            selections = _run_diff_tool(settings, tool, before, after)
        elif getattr(args, "interactive", False):
            print("Error: no diff editor specified; pass --tool",
                  file=sys.stderr)
            return 2
        # The destinations are computed inside the binding, so the
        # immutability check has to happen there too.
        stats = tx.absorb(settings, source, destinations=dest_expr, paths=paths,
                          check_immutable=not _ignore_immutable(),
                          selections=selections)
        _finish(tx, f"absorb changes into {len(stats.destinations)} commits",
                settings, ws, repo)
        return 0
