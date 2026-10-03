from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("fix", help="Update files with formatting fixes")
    add_flags(p, [Flag.SOURCE_REVSET, Flag.INCLUDE_UNCHANGED, Flag.FILESETS])
    p.add_argument("-a", "--all-lines", dest="all_lines",
                   action="store_true", default=False,
                   help="Format all lines instead of only modified lines")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.fix:fix")
