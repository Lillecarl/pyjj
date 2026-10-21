"""tag subcommand: tag_untrack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _track_remote,
    command,
)

if TYPE_CHECKING:
    import argparse


@command
def tag_untrack(args: argparse.Namespace) -> int:
    """`jj tag untrack TAG[@REMOTE]... [--remote REMOTE]`."""
    return _track_remote(args, "tag", "untrack")
