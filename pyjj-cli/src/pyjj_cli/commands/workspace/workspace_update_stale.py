"""workspace subcommand: workspace_update_stale."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _operation_args,
    _workspace_path,
    command,
    settings_for,
)

if TYPE_CHECKING:
    import argparse


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_update_stale(args: argparse.Namespace) -> int:
    """`jj workspace update-stale`.

    Loads the workspace without the snapshot every other command takes
    first: that snapshot refuses a stale working copy, which is the very
    state this command exists to fix. The binding snapshots the stale
    files at the working copy's own operation, so uncommitted edits
    survive, then checks out the fresh working-copy commit.
    """
    settings = settings_for(args)
    ws = pyjj.Workspace.load(settings, _workspace_path(args))
    _repo, checked_out = ws.recover_stale(settings, _operation_args())
    if checked_out is None:
        print("Attempted recovery, but the working copy is not stale.",
              file=sys.stderr)
        return 0
    # jj snapshots once more: the checkout may have imported git refs.
    ws.snapshot(settings, _operation_args())
    print(f"Updated working copy to fresh commit {checked_out.hex()[:12]}",
          file=sys.stderr)
    return 0
