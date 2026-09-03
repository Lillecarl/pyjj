"""templates subcommand: get."""
import subprocess
import sys

import pyjj
from ..common import _load


def templates_get(args) -> int:
    try:
        settings, _, _ = _load(args)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    name = getattr(args, "name")
    key = f"pyjj.templates.{name}"
    # Try via settings first (fast, no subprocess)
    try:
        val = settings.get_string(key)
        if val is not None:
            print(val)
            return 0
    except Exception:
        pass
    # Fallback to jj config get
    result = subprocess.run(["jj", "config", "get", key], capture_output=True, text=True)
    if result.returncode == 0:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        return 0
    print(f"Error: template '{name}' not found", file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return 1
