"""file subcommand: file_search."""
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

def file_search(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        pattern = getattr(args, "pattern", "")
        name_only = bool(getattr(args, "name_only", False))
        filesets = getattr(args, "filesets", None) or None
        # Simple search: list files and grep
        for path in commit.list_files(filesets):
            try:
                content = commit.read_file(path)
                if pattern.encode() in content:
                    print(f"{path}: {pattern}")
            except pyjj.JjError:
                continue
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
