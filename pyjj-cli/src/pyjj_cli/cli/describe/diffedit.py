from ..flags import Flag, add_flags, add_from_flag, add_to_flag


def register(sub) -> None:
    p = sub.add_parser("diffedit",
                       help="Edit the diff between two revisions in a diff editor")
    add_from_flag(p, default="@-", help="Show the diff FROM this revision (default: @-)")
    add_to_flag(p, dest="into", default="@", help="Apply edits TO this revision (default: @)")
    add_flags(p, [Flag.TOOL])
    p.set_defaults(_handler="pyjj_cli.commands.resolve.diffedit:diffedit")
