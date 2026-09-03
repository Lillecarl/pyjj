def register(sub) -> None:
    p = sub.add_parser("parallelize",
                       help="Parallelize revisions by making them siblings")
    p.add_argument("revisions_pos", nargs="*", metavar="REVSETS",
                   help="Revisions to parallelize (default: @)")
    p.add_argument("-r", "--revision", dest="revisions", action="append",
                   default=None, metavar="REVSETS",
                   help="Revisions to parallelize")
    p.set_defaults(_handler="pyjj_cli.commands.operation.parallelize:parallelize")
