"""util subcommand: snapshot — take a snapshot if the working copy moved.

Mirrors `cli/src/commands/util/snapshot.rs`. Every workspace command
already snapshots on load, so this only reports whether that snapshot
found anything.
"""
import sys

import pyjj

from ...commands.common import (CommandError, _operation_args,
                                _workspace_path, settings_for)


def util_snapshot(args) -> int:
    try:
        # Not `UserSettings()`: the snapshot honours settings the repo
        # layer can carry, `snapshot.max-new-file-size` among them, and
        # without that layer a file the limit forbids went in silently.
        settings = settings_for(args)
        ws = pyjj.Workspace.load(settings, _workspace_path(args))
        _repo, stats = ws.snapshot(settings, _operation_args())
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    print("Snapshot complete." if stats["changed"] else "No snapshot needed.")
    return 0
