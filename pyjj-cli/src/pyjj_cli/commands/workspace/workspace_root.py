"""workspace subcommand: workspace_root."""
import os
import sys

import pyjj
from ..common import (
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_root(args) -> int:
    _settings, ws, _repo = _load(args)
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
