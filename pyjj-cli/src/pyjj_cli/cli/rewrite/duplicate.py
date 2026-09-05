import argparse

from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to duplicate (default: @)")
    # jj hides `-r` here: the revisions are positional, and `-r` is what
    # a reader types out of habit. It keeps its own list, since an option
    # and a positional cannot share one.
    p.add_argument("-r", dest="revisions_opt", action="append", default=None,
                   metavar="REVSETS", help=argparse.SUPPRESS)
    p.add_argument("-o", "--onto", "-d", "--destination", dest="ontos",
                   action="append", default=None, metavar="REVSETS",
                   help="Revisions to duplicate onto")
    add_flags(p, [Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.duplicate:duplicate")
