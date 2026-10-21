"""operation subcommand: op_restore."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _resolve_operation,
    _restore_view_command,
    _restore_what,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def op_restore(args: argparse.Namespace) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    with write_tx(args) as (settings, ws, repo, tx):
        # `operation restore` names the same argument `operation`; the
        # short `op restore` form calls it `operation_pos`.
        name = (getattr(args, "operation_pos", None)
                or getattr(args, "operation", None))
        target = _resolve_operation(repo, name)
        tx.restore_operation(target, _restore_what(args))
        _restore_view_command(
            tx, f"restore operation {name}", settings, ws, repo
        )
        return 0
