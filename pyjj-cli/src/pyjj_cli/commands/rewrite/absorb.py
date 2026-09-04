"""pyjj-cli rewrite command: absorb."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _wc_commit,
    complete_newline,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def absorb(args) -> int:
    """`jj absorb --from X --into Y [FILESETS]` — move hunks into ancestors."""
    try:
        settings, ws, repo = _load(args)
        if getattr(args, "interactive", False) or getattr(args, "tool", None):
            print("Error: interactive absorb (--interactive/--tool) is not yet supported", file=sys.stderr)
            return 2
        source = _resolve_one(repo, settings, args.from_)
        dest_expr = getattr(args, "into", None)
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None
        tx = repo.start_transaction(settings)
        # The destinations are computed inside the binding, so the
        # immutability check has to happen there too.
        stats = tx.absorb(settings, source, destinations=dest_expr, paths=paths,
                          check_immutable=True)
        _finish(tx, f"absorb from {source.id.hex()[:12]} into {dest_expr or 'mutable()'}", settings, ws, repo)
        # Minimal feedback like jj (number of destinations)
        if stats.source is None:
            # Fully absorbed and abandoned (empty description)
            pass
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
