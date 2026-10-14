"""config subcommand: config_get."""
import sys

import pyjj
from ..common import (
    settings_for,
)

def config_get(args) -> int:
    try:
        settings = settings_for(args)
        val = settings.get_string(args.name)
        if val is None:
            print(f"Error: config {args.name} not set", file=sys.stderr)
            return 1
        print(val)
        return 0
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
