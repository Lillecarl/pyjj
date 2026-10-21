"""templates subcommand: get."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import _pyjj_template, command, read_repo

if TYPE_CHECKING:
    import argparse


@command
def templates_get(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, _):
        name = getattr(args, "name")
        value = _pyjj_template(settings, name, cwd=ws.workspace_root)
        if value is None:
            print(f"Error: template '{name}' not found", file=sys.stderr)
            return 1
        print(value)
        return 0
