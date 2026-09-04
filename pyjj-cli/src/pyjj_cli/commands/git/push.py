"""git subcommand: git_push."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
)

def git_push(args) -> int:
    """`jj git push` — push to a Git remote."""
    try:
        settings, ws, repo = _load(args)
        remote = getattr(args, "remote", None)
        if not remote:
            # Try to get default remote from settings or single remote
            try:
                all_remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = _start_transaction(repo, settings)
                all_remotes = tx.git_remotes()
            if len(all_remotes) == 1:
                remote = all_remotes[0]
            elif "origin" in all_remotes:
                remote = "origin"
            else:
                print("Error: no remote specified and no default found", file=sys.stderr)
                return 1
        bookmarks = getattr(args, "bookmarks", None) or []
        tags = getattr(args, "tags", None) or []
        all_flag = getattr(args, "all_flag", False)
        # For now, handle bookmarks; if --all, push all bookmarks
        tx = _start_transaction(repo, settings)
        if all_flag:
            # Push all bookmarks
            for bm in repo.bookmarks():
                try:
                    tx.git_push_bookmark(settings, remote, bm.name)
                except pyjj.JjError as e:
                    print(f"Warning: failed to push {bm.name}: {getattr(e, 'message', str(e))}", file=sys.stderr)
        elif bookmarks:
            for bm_name in bookmarks:
                try:
                    tx.git_push_bookmark(settings, remote, bm_name)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                    return 1
        elif tags:
            print("Error: pushing tags is not yet supported", file=sys.stderr)
            return 2
        else:
            # Default: push tracked bookmarks (simplified: push all)
            for bm in repo.bookmarks():
                try:
                    tx.git_push_bookmark(settings, remote, bm.name)
                except pyjj.JjError:
                    continue
        _finish(tx, f"push to {remote}", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
