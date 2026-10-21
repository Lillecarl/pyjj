"""templates subcommand: unset."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def templates_unset(args: argparse.Namespace) -> int:
    name = getattr(args, "name")
    is_repo = getattr(args, "repo", False)
    key = f"pyjj.templates.{name}"
    scope = "--repo" if is_repo else "--user"
    cwd = getattr(args, "repository", None) or "."
    result = subprocess.run(
        ["jj", "config", "unset", scope, key],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return result.returncode
    print(f"Unset {key}")
    return 0
