from ..flags import Flag, add_flags, add_from_flag, add_into_flag


def register(sub) -> None:
    p = sub.add_parser("restore", help="Restore paths from another revision")
    # Neither side has a default here. jj reads them together: naming
    # one defaults the other to `@`, and naming neither restores `@`
    # from the merge of its own parents.
    add_from_flag(p, help="Revision to restore from (source)")
    add_into_flag(p, help="Revision to restore into (destination)")
    p.add_argument("-c", "--changes-in", dest="changes_in", default=None,
                   metavar="REVSET",
                   help="Undo the changes in a revision, as compared to the "
                        "merge of its parents")
    add_flags(p, [Flag.TOOL])
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths to restore (default: all)")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.restore:restore")
