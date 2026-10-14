"""operation subcommand: op_abandon."""

from ..common import (
    command,
    read_repo,
)

@command
def op_abandon(args) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        ops = getattr(args, "operations", [])
        # Join with .. for range syntax if multiple
        if len(ops) == 1:
            op_str = ops[0]
        else:
            op_str = "..".join(ops)
        ws.op_abandon(op_str)
        return 0
