"""operation subcommand: redo."""

from ..common import (
    command,
)
from .op_diff import _restore_command

@command
def redo(args) -> int:
    return _restore_command(args, "redo")
