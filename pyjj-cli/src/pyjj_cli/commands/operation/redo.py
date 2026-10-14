"""operation subcommand: redo."""
import sys

import pyjj
from ...formatter import render_block
from ..common import (
    _start_transaction,
    CommandError,
    _load,
    _restore_view_command,
    use_color,
)
from .op_diff import _op_summary_spans

def redo(args) -> int:
    try:
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
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
