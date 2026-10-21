"""git subcommand: git_root."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_root(args: argparse.Namespace) -> int:
    """`jj git root` — show the underlying Git directory."""
    with read_repo(args) as (_settings, ws, _repo):
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
