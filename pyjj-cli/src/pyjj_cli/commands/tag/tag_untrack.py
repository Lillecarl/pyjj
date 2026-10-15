"""tag subcommand: tag_untrack."""

from ..common import (
    _track_remote,
    command,
)


@command
def tag_untrack(args) -> int:
    """`jj tag untrack TAG[@REMOTE]... [--remote REMOTE]`."""
    return _track_remote(args, "tag", "untrack")
