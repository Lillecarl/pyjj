"""operation subcommand: redo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    command,
)
from .op_diff import _restore_command

if TYPE_CHECKING:
    import argparse

@command
def redo(args: argparse.Namespace) -> int:
    return _restore_command(args, "redo")
