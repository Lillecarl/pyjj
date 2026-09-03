from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("split", help="Split a revision in two")
    p.add_argument("-r", "--revision", default=None, metavar="REVSETS",
                   help="Revision to split (default: @)")
    add_flags(p, [Flag.MESSAGE, Flag.TOOL])
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths going into the first half")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.split:split")
