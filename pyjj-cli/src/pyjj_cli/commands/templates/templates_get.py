"""templates subcommand: get."""
import sys

import pyjj
from ..common import _load, _pyjj_template


def templates_get(args) -> int:
    try:
        settings, ws, _ = _load(args)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    name = getattr(args, "name")
    value = _pyjj_template(settings, name, cwd=ws.workspace_root)
    if value is None:
        print(f"Error: template '{name}' not found", file=sys.stderr)
        return 1
    print(value)
    return 0
