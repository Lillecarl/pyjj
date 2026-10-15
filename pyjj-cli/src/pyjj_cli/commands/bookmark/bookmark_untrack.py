"""bookmark subcommand: bookmark_untrack."""

from ..common import (
    _track_remote,
    command,
)

@command
def bookmark_untrack(args) -> int:
    return _track_remote(args, "bookmark", "untrack")
