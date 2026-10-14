"""operation subcommand: op_restore."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _load,
    _resolve_operation,
    _restore_view_command,
    _restore_what,
)

def op_restore(args) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    try:
        settings, ws, repo = _load(args)
        # `operation restore` names the same argument `operation`; the
        # short `op restore` form calls it `operation_pos`.
        name = (getattr(args, "operation_pos", None)
                or getattr(args, "operation", None))
        target = _resolve_operation(repo, name)
        tx = _start_transaction(repo, settings)
        tx.restore_operation(target, _restore_what(args))
        _restore_view_command(
            tx, f"restore operation {name}", settings, ws, repo
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
