"""operation subcommand: op_abandon."""

from ..common import (
    _load,
    command,
)

@command
def op_abandon(args) -> int:
    _settings, ws, _repo = _load(args)
    ops = getattr(args, "operations", [])
    # Join with .. for range syntax if multiple
    if len(ops) == 1:
        op_str = ops[0]
    else:
        op_str = "..".join(ops)
    ws.op_abandon(op_str)
    return 0
