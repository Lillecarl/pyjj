"""tag subcommand: tag_track."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _track_remote,
    command,
)

if TYPE_CHECKING:
    import argparse


@command
def tag_track(args: argparse.Namespace) -> int:
    """`jj tag track TAG[@REMOTE]... [--remote REMOTE]`."""
    return _track_remote(args, "tag", "track")
