"""git subcommand: git_init."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
)

def git_init(args) -> int:
    """`jj git init` — create a new jj repo backed by Git.

    jj puts the git repo at the workspace root by default, so git tools
    see it too. `git.colocate = false` turns that off, and
    `--no-colocate` turns it off for one repo; `--colocate` only matters
    when the config already turned it off.
    """
    settings = pyjj.UserSettings()
    if getattr(args, "colocate", False) and getattr(args, "no_colocate", False):
        print("Error: --colocate cannot be used with --no-colocate",
              file=sys.stderr)
        return 2
    colocate = settings.get_bool("git.colocate")
    if colocate is None:
        colocate = True
    if getattr(args, "colocate", False):
        colocate = True
    if getattr(args, "no_colocate", False):
        colocate = False
    # Real `jj git init` creates missing parent directories.
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    init = (pyjj.Workspace.init_colocated_git if colocate
            else pyjj.Workspace.init_internal_git)
    try:
        ws, repo = init(settings, str(destination))
    except pyjj.WorkspaceInitError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Initialized repo in {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0
