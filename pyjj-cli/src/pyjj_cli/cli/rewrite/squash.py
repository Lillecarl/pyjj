from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("squash", help="Move changes from a revision into another")
    p.add_argument("-r", "--revision", action="append", default=None,
                   metavar="REVSETS", help="Source revisions (default: @)")
    p.add_argument("-f", "--from", dest="from_", action="append", default=None,
                   metavar="REVSETS", help="Source revisions")
    add_flags(p, [Flag.INTO, Flag.USE_DEST_MESSAGE, Flag.MESSAGE, Flag.FILESETS])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.squash:squash")
