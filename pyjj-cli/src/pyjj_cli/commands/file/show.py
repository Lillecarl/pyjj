"""file subcommand: file_show."""
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

def file_show(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        for pattern in args.filesets:
            # Support exact paths and directory filtering via list_files
            paths = commit.list_files([pattern])
            if not paths:
                # Try as exact file
                try:
                    content = commit.read_file(pattern)
                    sys.stdout.buffer.write(content)
                    if not content.endswith(b"\n"):
                        sys.stdout.buffer.write(b"\n")
                    continue
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
            for p in paths:
                try:
                    content = commit.read_file(p)
                    sys.stdout.buffer.write(content)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
