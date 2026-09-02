"""git subcommand: git_colocation."""
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

def git_colocation(args) -> int:
    """`jj git colocation` — manage colocation status."""
    try:
        _settings, ws, _repo = _load(args)
        sub = getattr(args, "colocation_command", None)
        ws_root = Path(ws.workspace_root)
        git_dir = ws_root / ".git"
        is_colocated = git_dir.exists()
        if sub == "status":
            if is_colocated:
                print("Colocated with Git")
            else:
                print("Not colocated with Git")
            return 0
        elif sub == "enable":
            if is_colocated:
                print("Already colocated", file=sys.stderr)
                return 0
            # Enabling colocation would require moving the git dir from .jj/repo/store/git to .git
            # This is not yet implemented in pyjj — we just report and return error
            print("Error: converting to colocated repo is not yet supported", file=sys.stderr)
            return 1
        elif sub == "disable":
            if not is_colocated:
                print("Already not colocated", file=sys.stderr)
                return 0
            print("Error: converting to non-colocated repo is not yet supported", file=sys.stderr)
            return 1
        else:
            print("usage: pyjj git colocation {status,enable,disable}", file=sys.stderr)
            return 2
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
