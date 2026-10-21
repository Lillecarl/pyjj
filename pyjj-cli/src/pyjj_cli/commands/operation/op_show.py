"""operation subcommand: op show — one operation, and what it changed.

Mirrors `cli/src/commands/operation/show.rs`. jj renders the header
with the same `builtin_op_log_compact` template `op log` uses, without
the graph, and then prints the operation's own diff below it -- so this
is `op log`'s header plus `op diff`'s body, and both come from there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import _resolve_operation, command, read_repo, use_color
from .op_diff import print_operation_diff
from .op_log import _shape, render_operation

if TYPE_CHECKING:
    import argparse


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def op_show(args: argparse.Namespace) -> int:
    """`jj op show` — an operation's header, then what it changed."""
    with read_repo(args) as (settings, ws, repo):
        op = _resolve_operation(repo, getattr(args, "operation", None))
        shape, template = _shape(settings, ws, args, "op_show")
        print(render_operation(op, op.id == repo.operation.id, shape,
                               template, "op_show", use_color(settings)))
        if getattr(args, "no_op_diff", False):
            return 0
        # An operation's diff is against its parents, which is what
        # `op diff` computes when given no --from/--to.
        return print_operation_diff(args, settings, ws, repo, op.parents(),
                                    op, heading=False, prefix="op_show")
