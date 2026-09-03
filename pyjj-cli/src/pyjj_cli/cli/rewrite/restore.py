from ..flags import add_from_flag, add_into_flag


def register(sub) -> None:
    p = sub.add_parser("restore", help="Restore paths from another revision")
    add_from_flag(p, default="@-", help="Revision to restore from (default: @-)")
    add_into_flag(p, default="@", help="Revision to restore into (default: @)")
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths to restore (default: all)")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.restore:restore")
