"""workspace subcommand: workspace_update_stale."""

import pyjj
from ..common import (
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_update_stale(args) -> int:
    with read_repo(args) as (settings, ws, repo):
        # repo is already at head via _load, so we can check if ws is stale
        result = ws.update_stale(repo)
        if result is None:
            print("Working copy is not stale")
        else:
            print(f"Updated stale working copy: {result}")
        return 0
