"""workspace subcommand: workspace_update_stale."""
import sys

import pyjj
from ..common import (
    _load,
)

def workspace_update_stale(args) -> int:
    try:
        settings, ws, repo = _load(args)
        # repo is already at head via _load, so we can check if ws is stale
        result = ws.update_stale(repo)
        if result is None:
            print("Working copy is not stale")
        else:
            print(f"Updated stale working copy: {result}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
