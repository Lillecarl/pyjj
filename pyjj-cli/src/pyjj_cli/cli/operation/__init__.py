from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
# cli/operation package — one module per subcommand.


def _op_help(args: argparse.Namespace):
    import sys
    print("usage: pyjj op {restore}", file=sys.stderr)
    return 2


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    from . import evolog, interdiff, next, op, parallelize, prev, redo, undo

    undo.register(sub)
    redo.register(sub)
    op.register(sub)
    evolog.register(sub)
    next.register(sub)
    prev.register(sub)
    parallelize.register(sub)
    interdiff.register(sub)
