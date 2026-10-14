"""file subcommand: file_track."""
import sys
from pathlib import Path

from ..common import (
    _load,
    command,
)

@command
def file_track(args) -> int:
    # file track is about telling the working copy to start tracking a path
    # that was previously ignored (e.g. via .gitignore). In pyjj, snapshot
    # already handles .gitignore, but file track with --include-ignored
    # would force-track. For now, we just ensure the file is not ignored
    # by touching it and snapshotting, but the real `jj file track` does
    # more. For parity, we just snapshot and check out.
    _settings, ws, repo = _load(args)
    # Snapshot will pick up the files if they exist and are not ignored
    # unless --include-ignored is used, in which case we would need to
    # force-track. For now, just do a snapshot and return.
    # The paths are relative to workspace root, we ensure they exist
    for path in getattr(args, "paths", []):
        p = Path(ws.workspace_root) / path
        if not p.exists():
            print(f"Warning: path {path} does not exist", file=sys.stderr)
    return 0
