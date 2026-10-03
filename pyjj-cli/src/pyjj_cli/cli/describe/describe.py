import argparse

from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("describe", aliases=["desc"], help="Set commit descriptions")
    p.add_argument("-r", "--revision", dest="revisions_opt", action="append",
                   default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to describe (default: @)")
    add_flags(p, [Flag.MESSAGE_APPEND, Flag.STDIN])
    p.add_argument("--editor", dest="editor", action="store_true",
                   default=False,
                   help="Open an editor to edit the description, "
                        "pre-filled with -m or the current text")
    p.set_defaults(_handler="pyjj_cli.commands.describe.describe:describe")
