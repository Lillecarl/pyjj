"""util subcommand: backend name — which storage format the repo uses.

Mirrors `cli/src/commands/util/backend/name.rs`. Like `util exec`, jj
reaches for the no-snapshot helper here, so this leaves the working copy
alone.
"""
import sys

import pyjj

from ...commands.common import CommandError, _workspace_path


def util_backend_name(args) -> int:
    try:
        settings = pyjj.UserSettings()
        ws = pyjj.Workspace.load(settings, _workspace_path(args))
        repo = ws.load_at_head()
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    print(repo.backend_name)
    return 0
