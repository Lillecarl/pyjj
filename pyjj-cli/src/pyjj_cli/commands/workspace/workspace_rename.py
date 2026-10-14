"""workspace subcommand: workspace_rename."""

import pyjj
from ..common import (
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_rename(args) -> int:
    settings, ws, _repo = _load(args)
    new_name = getattr(args, "new_name", "")
    ws.rename_workspace(settings, new_name)
    return 0
