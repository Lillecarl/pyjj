from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("resolve",
                       help="Resolve conflicted files with an external merge tool")
    p.add_argument("-r", "--revision", default="@", metavar="REVSET",
                   help="The revision to resolve conflicts in (default: @)")
    p.add_argument("-l", "--list", dest="list_", action="store_true",
                   help="Instead of resolving conflicts, list all the conflicts")
    add_flags(p, [Flag.TOOL])
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Only resolve conflicts in these paths")
    p.set_defaults(_handler="pyjj_cli.commands.resolve.resolve:resolve")
