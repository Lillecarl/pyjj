import argparse

from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                   help="Parent revisions (default: @)")
    # jj hides these two: the parents are positional, and `-o` and `-r`
    # are what a reader types out of habit. They keep their own list,
    # since an option and a positional cannot share one.
    p.add_argument("-o", "-r", dest="parents_opt", action="append",
                   default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                   help="Description of the new change")
    p.add_argument("--no-edit", dest="no_edit", action="store_true", default=False,
                   help="Do not edit the newly created change")
    add_flags(p, [Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.describe.new:new")
