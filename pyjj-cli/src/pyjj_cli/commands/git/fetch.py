"""git subcommand: git_fetch."""
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

def git_fetch(args) -> int:
    """`jj git fetch` — fetch from a Git remote."""
    try:
        settings, ws, repo = _load(args)
        # Determine remotes
        remotes: list[str] = []
        if getattr(args, "all_remotes", False):
            try:
                remotes = repo.git_remotes()  # type: ignore[attr-defined] - on ReadonlyRepo via Transaction?
            except Exception:
                # Fallback: try via transaction
                tx = repo.start_transaction(settings)
                remotes = tx.git_remotes()
        elif getattr(args, "remote", None):
            remotes = [args.remote]
        else:
            # Default: try to get all remotes, if single, use it, else "origin"
            try:
                all_remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = repo.start_transaction(settings)
                all_remotes = tx.git_remotes()
            if len(all_remotes) == 1:
                remotes = all_remotes
            elif "origin" in all_remotes:
                remotes = ["origin"]
            elif all_remotes:
                remotes = [all_remotes[0]]
            else:
                print("Error: no git remotes configured", file=sys.stderr)
                return 1

        branches = getattr(args, "branches", None) or []
        # For now, handle branches as bookmark names to fetch
        # If no branches specified, fetch all (via git_fetch_all)
        tx = repo.start_transaction(settings)
        for remote in remotes:
            try:
                if branches:
                    # Fetch specific branches
                    result = tx.git_fetch(settings, remote, branches)
                else:
                    result = tx.git_fetch_all(settings, remote)
                # result is a dict with stats, we could print it
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
        _finish(tx, f"fetch from {', '.join(remotes)}", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
