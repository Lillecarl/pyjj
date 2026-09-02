"""git subcommand: git_root."""
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

def git_root(args) -> int:
    """`jj git root` — show the underlying Git directory."""
    try:
        _settings, ws, _repo = _load(args)
        # Try to find .git directory
        ws_root = Path(ws.workspace_root)
        # Check for colocated .git
        git_dir = ws_root / ".git"
        if git_dir.exists():
            print(str(git_dir.resolve()))
            return 0
        # Otherwise, it's stored in .jj/repo/store/git
        repo_path = Path(ws.repo_path)
        git_store = repo_path / "store" / "git"
        if git_store.exists():
            print(str(git_store.resolve()))
            return 0
        # Fallback to repo_path
        print(str(repo_path))
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
