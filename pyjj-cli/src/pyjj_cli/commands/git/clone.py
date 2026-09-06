"""git subcommand: git_clone."""
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

def git_clone(args) -> int:
    """`jj git clone <source> [destination]` — clone a Git repo."""
    settings = pyjj.UserSettings()
    source = args.source
    # Derive destination from source if not provided, like real jj does
    if args.destination:
        dest = Path(args.destination).resolve()
    else:
        # Take last component of source URL/path, strip .git suffix
        src = source.rstrip("/")
        # Handle URLs like https://github.com/user/repo.git
        # Take after last slash or colon
        if "/" in src:
            base = src.rsplit("/", 1)[-1]
        elif ":" in src:
            base = src.rsplit(":", 1)[-1]
        else:
            base = src
        if base.endswith(".git"):
            base = base[:-4]
        if not base:
            base = "repo"
        dest = Path.cwd() / base
        dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    # Check if dest is empty
    if any(dest.iterdir()):
        print(f"Error: destination path exists and is not an empty directory: {dest}", file=sys.stderr)
        return 1
    colocate = getattr(args, "colocate", True)
    remote_name = getattr(args, "remote_name", "origin") or "origin"
    try:
        ws, repo = pyjj.Workspace.clone_git(
            settings, source, str(dest), remote_name=remote_name,
            colocate=colocate,
            branches=list(getattr(args, "branches", None) or []) or None,
            depth=getattr(args, "depth", None),
            fetch_tags=getattr(args, "fetch_tags", None))
    except (pyjj.WorkspaceInitError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    print(f"Fetched repo from {source} into {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0
