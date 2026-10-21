"""workspace subcommand: workspace_forget."""

from __future__ import annotations

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
def workspace_forget(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, repo):
        view = repo.view()
        names = getattr(args, "names", [])
        known = [name for name in names if name in view]
        for name in names:
            if name not in view:
                print(f"Warning: No such workspace: {name}", file=sys.stderr)
        if not known:
            if names:
                print("Nothing changed.", file=sys.stderr)
            else:
                # No names at all: the binding refuses an empty batch.
                ws.forget_workspaces(settings, names)
            return 0
        # The recorded path intentionally outlives the forget (undoing
        # it restores the workspace, which needs the directory), so
        # the entry is kept -- unlike `remove`, which drops it.
        ws.forget_workspaces(settings, known, forget_store=False)
        for name in known:
            _unlink_worktree(settings, ws, name)
        return 0


def _unlink_worktree(settings: pyjj.UserSettings, ws: pyjj.Workspace, name: str) -> None:
    """Drop the Git worktree backing a forgotten workspace, if any.

    A leftover gitlink or stale metadata is not worth failing over,
    so errors become warnings -- jj's `unlink_git_worktree` contract.
    """
    try:
        recorded = ws.workspace_path(name)
    except pyjj.JjError:
        return
    if recorded is None:
        return
    try:
        removed = ws.unlink_git_worktree(settings, recorded)
    except pyjj.JjError as e:
        print(f"Warning: Failed to remove Git worktree for \"{recorded}\".",
              file=sys.stderr)
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return
    if removed:
        print(f"Removed Git worktree for \"{recorded}\".")
