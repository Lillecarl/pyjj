def register(sub) -> None:
    p = sub.add_parser("edit", help="Edit (check out) a specific revision")
    p.add_argument("revision_pos", metavar="REVSETS",
                   help="The revision to edit")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.edit:edit")
