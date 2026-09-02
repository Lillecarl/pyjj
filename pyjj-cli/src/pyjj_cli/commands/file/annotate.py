"""file subcommand: file_annotate."""
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

def file_annotate(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        lines = commit.annotate(repo, args.path)
        for ann in lines:
            prefix = f"{ann.commit_id.hex()[:12]}"
            sys.stdout.buffer.write(prefix.encode() + b"  " + ann.line)
            if not ann.line.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
