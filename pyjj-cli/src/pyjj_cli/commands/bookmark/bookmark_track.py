"""bookmark subcommand: bookmark_track."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _track_remote,
    command,
)

if TYPE_CHECKING:
    import argparse

@command
def bookmark_track(args: argparse.Namespace) -> int:
    return _track_remote(args, "bookmark", "track")
