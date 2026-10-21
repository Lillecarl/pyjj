"""workspace subcommand: workspace_rename."""

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
def workspace_rename(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, _repo):
        new_name = getattr(args, "new_name", "")
        ws.rename_workspace(settings, new_name)
        return 0
