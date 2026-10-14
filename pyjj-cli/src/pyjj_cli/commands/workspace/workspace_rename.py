"""workspace subcommand: workspace_rename."""
import sys

import pyjj
from ..common import (
    _load,
)

def workspace_rename(args) -> int:
    try:
        settings, ws, _repo = _load(args)
        new_name = getattr(args, "new_name", "")
        ws.rename_workspace(settings, new_name)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
