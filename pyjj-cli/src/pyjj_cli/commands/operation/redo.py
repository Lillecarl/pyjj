"""operation subcommand: redo."""

from ...formatter import render_block
from ..common import (
    _restore_view_command,
    use_color,
    command,
    write_tx,
)
from .op_diff import _op_summary_spans

@command
def redo(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        _redone, restored_to, description = tx.redo(
            ws.workspace_name, getattr(args, "allow_cross_workspace", False))
        coloured = use_color(settings)
        print(render_block(
            [[("Restored to operation: ", ""),
              *_op_summary_spans(restored_to, "")]],
            (), coloured))
        _restore_view_command(tx, description, settings, ws, repo)
        return 0
