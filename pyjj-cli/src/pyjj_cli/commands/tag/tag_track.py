"""tag subcommand: tag_track."""

from ..common import (
    _track_remote,
    command,
)


@command
def tag_track(args) -> int:
    """`jj tag track TAG[@REMOTE]... [--remote REMOTE]`."""
    return _track_remote(args, "tag", "track")
