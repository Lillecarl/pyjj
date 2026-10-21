"""workspace subcommand: workspace_update_stale."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_update_stale(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, repo):
        # repo is already at head via _load, so we can check if ws is stale
        result = ws.update_stale(repo)
        if result is None:
            print("Working copy is not stale")
        else:
            print(f"Updated stale working copy: {result}")
        return 0
