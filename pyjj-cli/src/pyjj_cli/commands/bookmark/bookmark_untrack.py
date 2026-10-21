"""bookmark subcommand: bookmark_untrack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _track_remote,
    command,
)

if TYPE_CHECKING:
    import argparse

@command
def bookmark_untrack(args: argparse.Namespace) -> int:
    return _track_remote(args, "bookmark", "untrack")
