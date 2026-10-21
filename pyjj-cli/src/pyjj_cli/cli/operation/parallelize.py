from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("parallelize",
                       help="Parallelize revisions by making them siblings")
    p.add_argument("revisions_pos", nargs="*", metavar="REVSETS",
                   help="Revisions to parallelize (default: @)")
    p.add_argument("-r", "--revision", dest="revisions", action="append",
                   default=None, metavar="REVSETS",
                   help="Revisions to parallelize")
    p.set_defaults(_handler="pyjj_cli.commands.operation.parallelize:parallelize")
