"""config subcommand: config_get."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    settings_for,
)

if TYPE_CHECKING:
    import argparse

@command
def config_get(args: argparse.Namespace) -> int:
    settings = settings_for(args)
    try:
        val = settings.get_string(args.name)
    except pyjj.JjError:
        # Not a string: jj prints the value in its TOML form, which is
        # what the winning layer's entry holds.
        val = next((layer.entries[args.name]
                    for layer in reversed(settings.config_layers())
                    if args.name in layer.entries), None)
        if val is None:
            raise
    if val is None:
        print(f"Error: config {args.name} not set", file=sys.stderr)
        return 1
    print(val)
    return 0
