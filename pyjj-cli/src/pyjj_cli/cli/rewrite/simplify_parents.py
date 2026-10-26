from __future__ import annotations

from typing import TYPE_CHECKING

from ..flags import Flag, add_flags

if TYPE_CHECKING:
    import argparse
def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("simplify-parents",
                       help="Simplify parent edges for the specified revision(s)")
    p.add_argument("-s", "--source", dest="sources", action="append", default=None,
                   metavar="REVSETS",
                   help="Simplify these revisions and their descendants")
    p.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                   metavar="REVSETS", help="Simplify these revisions")
    add_flags(p, [Flag.TRIAL])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.simplify_parents:simplify_parents")
