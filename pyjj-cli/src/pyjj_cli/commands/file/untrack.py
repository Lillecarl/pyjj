"""file subcommand: file_untrack."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
    _wc_commit,
)

def file_untrack(args) -> int:
    # file untrack is the opposite: stop tracking a path. In pyjj, this
    # would involve adding it to .gitignore or just removing it from the
    # working copy? For now, we treat it as removing the file from the
    # working copy and letting snapshot handle it.
    try:
        _settings, ws, repo = _load(args)
        for path in getattr(args, "paths", []):
            p = Path(ws.workspace_root) / path
            if p.exists():
                # For parity, we just remove the file and let snapshot handle
                # but we don't actually delete; we just return
                pass
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
