"""crypto subcommand: unsign."""

from ..common import (
    _rewrite_signatures,
    command,
)

@command
def unsign(args) -> int:
    return _rewrite_signatures(args, "unsign", "drop", signed_only=True)
