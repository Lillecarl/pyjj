from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("split", help="Split a revision in two")
    p.add_argument("-r", "--revision", default=None, metavar="REVSETS",
                   help="Revision to split (default: @)")
    p.add_argument("-p", "--parallel", dest="parallel", action="store_true",
                   default=False,
                   help="Make the two halves siblings instead of a chain")
    add_flags(p, [Flag.MESSAGE, Flag.EDITOR, Flag.TOOL, Flag.DESTINATION,
                  Flag.ONTO, Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths going into the first half")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.split:split")
