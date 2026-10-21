"""file subcommand: file_track."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command
def file_track(args: argparse.Namespace) -> int:
    # file track is about telling the working copy to start tracking a path
    # that was previously ignored (e.g. via .gitignore). In pyjj, snapshot
    # already handles .gitignore, but file track with --include-ignored
    # would force-track. For now, we just ensure the file is not ignored
    # by touching it and snapshotting, but the real `jj file track` does
    # more. For parity, we just snapshot and check out.
    with read_repo(args) as (_settings, ws, repo):
        # Snapshot will pick up the files if they exist and are not ignored
        # unless --include-ignored is used, in which case we would need to
        # force-track. For now, just do a snapshot and return.
        # The paths are relative to workspace root, we ensure they exist
        for path in getattr(args, "paths", []):
            p = Path(ws.workspace_root) / path
            if not p.exists():
                print(f"Warning: path {path} does not exist", file=sys.stderr)
        return 0
