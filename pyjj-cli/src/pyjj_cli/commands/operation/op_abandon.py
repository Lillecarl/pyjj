"""operation subcommand: op_abandon."""
import sys

import pyjj
from ..common import (
    CommandError,
    _load,
)

def op_abandon(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        ops = getattr(args, "operations", [])
        # Join with .. for range syntax if multiple
        if len(ops) == 1:
            op_str = ops[0]
        else:
            op_str = "..".join(ops)
        ws.op_abandon(op_str)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
