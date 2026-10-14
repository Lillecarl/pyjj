"""bookmark subcommand: bookmark_track."""

from ..common import (
    _finish,
    _split_remote_ref,
    command,
    write_tx,
)

@command
def bookmark_track(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        default_remote = getattr(args, "remote", None)
        for name in getattr(args, "names", []):
            bookmark, remote = _split_remote_ref(name, default_remote)
            tx.git_track_remote_bookmark(remote, bookmark)
        _finish(tx, f"track remote bookmark {', '.join(getattr(args, 'names', []))}",
                settings, ws, repo)
        return 0
