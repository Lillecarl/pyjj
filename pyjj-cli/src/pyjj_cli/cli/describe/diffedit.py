from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("diffedit",
                       help="Edit the diff between two revisions in a diff editor")
    p.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                   help="Show the diff FROM this revision (default: @-)")
    p.add_argument("--to", dest="into", default="@", metavar="REVSET",
                   help="Apply edits TO this revision (default: @)")
    add_flags(p, [Flag.TOOL])
    p.set_defaults(_handler="pyjj_cli.commands.resolve.diffedit:diffedit")
