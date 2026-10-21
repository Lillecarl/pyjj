"""workspace subcommand: workspace_root."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_root(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        name = getattr(args, "name", None)
        if not name:
            print(ws.workspace_root)
            return 0
        rel = ws.workspace_path(name)
        if rel is None:
            print(f"Error: No such workspace: {name}", file=sys.stderr)
            return 1
        # The store records the path relative to `.jj/repo`.
        print(os.path.normpath(os.path.join(ws.repo_path, rel)))
        return 0
