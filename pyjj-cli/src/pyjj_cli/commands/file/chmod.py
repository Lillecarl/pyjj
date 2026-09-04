"""file subcommand: file_chmod."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
    _wc_commit,
)

def file_chmod(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        mode = getattr(args, "mode", "x")
        executable = mode in ("x", "executable")
        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [commit])
        for path in getattr(args, "paths", []):
            b = tx.set_executable(commit, path, executable)
            b.write(repo)
        _finish(tx, f"chmod {rev}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
