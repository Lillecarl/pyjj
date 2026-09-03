def register(sub) -> None:
    p = sub.add_parser("restore", help="Restore paths from another revision")
    p.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                   help="Revision to restore from (default: @-)")
    p.add_argument("--into", dest="into", default="@", metavar="REVSET",
                   help="Revision to restore into (default: @)")
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths to restore (default: all)")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.restore:restore")
