"""config subcommand: config_get."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    command,
    settings_for,
)

if TYPE_CHECKING:
    import argparse

@command
def config_get(args: argparse.Namespace) -> int:
    settings = settings_for(args)
    val = settings.get_string(args.name)
    if val is None:
        print(f"Error: config {args.name} not set", file=sys.stderr)
        return 1
    print(val)
    return 0
