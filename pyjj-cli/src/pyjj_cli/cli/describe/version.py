from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("version", help="Show version information")
    p.set_defaults(_handler="pyjj_cli.commands.crypto.version:version")
