from ..flags import Flag, add_flags, add_from_flag, add_to_flag


def register(sub) -> None:
    p = sub.add_parser("diffedit",
                       help="Edit the diff between two revisions in a diff editor")
    # `-r` edits a revision against the merge of its parents; `--from`
    # and `--to` edit the diff between two revisions. Naming one of the
    # latter defaults the other to `@`, and naming none of the three is
    # `-r @`.
    p.add_argument("-r", "--revision", dest="revision", default=None,
                   metavar="REVSET", help="The revision to touch up (default: @)")
    add_from_flag(p, help="Show changes from this revision")
    add_to_flag(p, dest="into", help="Edit changes in this revision")
    add_flags(p, [Flag.TOOL])
    p.set_defaults(_handler="pyjj_cli.commands.resolve.diffedit:diffedit")
