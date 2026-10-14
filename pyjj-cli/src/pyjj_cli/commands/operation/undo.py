"""operation subcommand: undo."""
import sys

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
def undo(args) -> int:
    settings, ws, repo = _load(args)
    tx = _start_transaction(repo, settings)
    undone, restored_to, description = tx.undo(
        ws.workspace_name, getattr(args, "allow_cross_workspace", False))
    if undone.description.startswith("remove workspace"):
        print("Warning: Undoing a workspace removal restores the "
              "workspace, but does not restore the workspace directory.",
              file=sys.stderr)
        print("Hint: Run `jj workspace forget` then `jj workspace add` "
              "to recreate the directory.", file=sys.stderr)
    coloured = use_color(settings)
    print(render_block(
        [[("Undid operation: ", ""), *_op_summary_spans(undone, "")]],
        (), coloured))
    print(render_block(
        [[("Restored to operation: ", ""),
          *_op_summary_spans(restored_to, "")]],
        (), coloured))
    _restore_view_command(tx, description, settings, ws, repo)
    return 0
