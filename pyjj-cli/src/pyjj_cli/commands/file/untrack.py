"""file subcommand: file_untrack."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import CommandError, read_repo

if TYPE_CHECKING:
    import argparse

def file_untrack(args: argparse.Namespace) -> int:
    """`jj file untrack <paths>`: stop tracking paths in the working copy.

    The files stay on disk. A path that is not ignored is added straight
    back by the snapshot that follows, and jj then writes nothing at all
    -- the binding does the whole thing in one operation so it can abort
    before either half lands.
    """
    paths = list(getattr(args, "paths", []) or [])
    if not paths:
        print("Error: Paths to untrack are required", file=sys.stderr)
        return 2
    try:
        with read_repo(args) as (settings, ws, _repo):
            _repo, added_back = ws.untrack_paths(settings, paths)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    if added_back:
        print(f"Error: '{added_back[0]}' is not ignored.", file=sys.stderr)
        print("Hint: Files that are not ignored will be added back by the "
              "next command.", file=sys.stderr)
        return 1
    return 0
