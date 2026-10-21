"""crypto subcommand: unsign."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _rewrite_signatures,
    command,
)

if TYPE_CHECKING:
    import argparse

@command
def unsign(args: argparse.Namespace) -> int:
    return _rewrite_signatures(args, "unsign", "drop", signed_only=True)
