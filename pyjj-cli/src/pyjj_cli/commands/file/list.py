"""file subcommand: file_list."""
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

def file_list(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        paths = getattr(args, "filesets", None) or None
        for p in sorted(commit.list_files(paths)):
            print(p)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
