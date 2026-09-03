def register(sub) -> None:
    p = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to duplicate (default: @)")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.duplicate:duplicate")
