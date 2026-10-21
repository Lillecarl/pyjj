from __future__ import annotations

from typing import TYPE_CHECKING

from ..flags import Flag, add_flags

if TYPE_CHECKING:
    import argparse


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("absorb", help="Move changes from a revision into ancestors")
    p.add_argument("-f", "--from", dest="from_", default="@", metavar="REVSET",
                   help="Source revision to absorb from (default: @)")
    p.add_argument("-t", "--into", "--to", dest="into", default=None, metavar="REVSETS",
                   help="Destination revisions to absorb into (default: mutable())")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="Interactively choose which parts to absorb")
    add_flags(p, [Flag.TOOL, Flag.FILESETS])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.absorb:absorb")
