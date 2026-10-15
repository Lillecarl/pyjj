"""bookmark subcommand: bookmark_track."""

from ..common import (
    _track_remote,
    command,
)

@command
def bookmark_track(args) -> int:
    return _track_remote(args, "bookmark", "track")
