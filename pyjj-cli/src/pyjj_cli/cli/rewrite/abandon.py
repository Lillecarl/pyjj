def register(sub) -> None:
    p = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to abandon (default: @)")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.abandon:abandon")
