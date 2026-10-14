"""operation subcommand: redo."""

from ...formatter import render_block
from ..common import (
    _start_transaction,
    _load,
    _restore_view_command,
    use_color,
    command,
)
from .op_diff import _op_summary_spans

@command
def redo(args) -> int:
    settings, ws, repo = _load(args)
    tx = _start_transaction(repo, settings)
    _redone, restored_to, description = tx.redo(
        ws.workspace_name, getattr(args, "allow_cross_workspace", False))
    coloured = use_color(settings)
    print(render_block(
        [[("Restored to operation: ", ""),
          *_op_summary_spans(restored_to, "")]],
        (), coloured))
    _restore_view_command(tx, description, settings, ws, repo)
    return 0
