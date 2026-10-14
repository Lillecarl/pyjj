"""workspace subcommand: workspace_rename."""

import pyjj
from ..common import (
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_rename(args) -> int:
    with read_repo(args) as (settings, ws, _repo):
        new_name = getattr(args, "new_name", "")
        ws.rename_workspace(settings, new_name)
        return 0
