"""operation subcommand: undo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    command,
)
from .op_diff import _restore_command

if TYPE_CHECKING:
    import argparse

@command
def undo(args: argparse.Namespace) -> int:
    return _restore_command(args, "undo")
