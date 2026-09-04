"""util subcommand: snapshot — take a snapshot if the working copy moved.

Mirrors `cli/src/commands/util/snapshot.rs`. Every workspace command
already snapshots on load, so this only reports whether that snapshot
found anything.
"""
import sys

import pyjj

from ...commands.common import CommandError, _workspace_path


def util_snapshot(args) -> int:
    try:
        settings = pyjj.UserSettings()
        ws = pyjj.Workspace.load(settings, _workspace_path(args))
        _repo, stats = ws.snapshot(settings)
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    print("Snapshot complete." if stats["changed"] else "No snapshot needed.")
    return 0
