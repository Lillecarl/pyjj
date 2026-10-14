"""config subcommand: config_get."""
import sys

from ..common import (
    settings_for,
    command,
)

@command
def config_get(args) -> int:
    settings = settings_for(args)
    val = settings.get_string(args.name)
    if val is None:
        print(f"Error: config {args.name} not set", file=sys.stderr)
        return 1
    print(val)
    return 0
