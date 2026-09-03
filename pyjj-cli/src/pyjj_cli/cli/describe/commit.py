from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("commit",
                       help="Describe @ and create a new empty change on top")
    add_flags(p, [Flag.MESSAGE])
    p.add_argument("--editor", action="store_true",
                   help="Open an editor to edit the description")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="Interactively choose which changes to include")
    add_flags(p, [Flag.TOOL])
    p.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                   help="Paths staying in the current commit")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.commit:commit")
