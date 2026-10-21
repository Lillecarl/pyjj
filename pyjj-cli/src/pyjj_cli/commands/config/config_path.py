"""config subcommand: config_path."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import CommandError
from .config_set import _scope, _workspace_root
from .paths import config_path

if TYPE_CHECKING:
    import argparse


def config_path_command(args: argparse.Namespace) -> int:
    """`jj config path --repo|--user|--workspace`."""
    scope = _scope(args)
    if scope is None:
        print("Error: No config target given; pass --user, --repo or --workspace",
              file=sys.stderr)
        return 2
    try:
        root = _workspace_root(args) if scope != "user" else None
        # jj creates the scope here rather than reporting nothing.
        print(config_path(root, scope, create=True))
    except (pyjj.JjError, CommandError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    return 0
