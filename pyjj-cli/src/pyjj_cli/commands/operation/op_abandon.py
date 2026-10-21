"""operation subcommand: op_abandon."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command
def op_abandon(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        ops = getattr(args, "operations", [])
        # Join with .. for range syntax if multiple
        if len(ops) == 1:
            op_str = ops[0]
        else:
            op_str = "..".join(ops)
        stats = ws.op_abandon(op_str)
        if stats.unmapped_working_copy_operation is not None:
            print(f"Warning: The working copy operation "
                  f"{stats.unmapped_working_copy_operation[:12]} is not updated "
                  "because it differs from the repo.", file=sys.stderr)
        return 0
