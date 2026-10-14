"""pyjj-cli rewrite command: absorb."""
import sys

from ..common import (
    _finish,
    _ignore_immutable,
    _resolve_one,
    command,
    write_tx,
)

@command
def absorb(args) -> int:
    """`jj absorb --from X --into Y [FILESETS]` — move hunks into ancestors."""
    with write_tx(args) as (settings, ws, repo, tx):
        if getattr(args, "interactive", False) or getattr(args, "tool", None):
            print("Error: interactive absorb (--interactive/--tool) is not yet supported", file=sys.stderr)
            return 2
        source = _resolve_one(repo, settings, args.from_)
        dest_expr = getattr(args, "into", None)
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None
        # The destinations are computed inside the binding, so the
        # immutability check has to happen there too.
        stats = tx.absorb(settings, source, destinations=dest_expr, paths=paths,
                          check_immutable=not _ignore_immutable())
        _finish(tx, f"absorb from {source.id.hex()[:12]} into {dest_expr or 'mutable()'}", settings, ws, repo)
        # Minimal feedback like jj (number of destinations)
        if stats.source is None:
            # Fully absorbed and abandoned (empty description)
            pass
        return 0
        return 0
