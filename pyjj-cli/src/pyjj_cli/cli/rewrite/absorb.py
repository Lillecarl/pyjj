from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("absorb", help="Move changes from a revision into ancestors")
    p.add_argument("-f", "--from", dest="from_", default="@", metavar="REVSET",
                   help="Source revision to absorb from (default: @)")
    p.add_argument("-t", "--into", "--to", dest="into", default=None, metavar="REVSETS",
                   help="Destination revisions to absorb into (default: mutable())")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="Interactively choose which parts to absorb")
    add_flags(p, [Flag.TOOL, Flag.FILESETS])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.absorb:absorb")
