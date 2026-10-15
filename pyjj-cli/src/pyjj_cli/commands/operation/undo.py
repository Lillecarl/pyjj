"""operation subcommand: undo."""

from ..common import (
    command,
)
from .op_diff import _restore_command

@command
def undo(args) -> int:
    return _restore_command(args, "undo")
