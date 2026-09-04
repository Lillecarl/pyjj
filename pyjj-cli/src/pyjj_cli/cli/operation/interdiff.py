from ..flags import (
    add_git_flag,
    add_name_only_flag,
    add_stat_flag,
    add_summary_flag,
)


def register(sub) -> None:
    p = sub.add_parser("interdiff",
                       help="Show differences between the diffs of two revisions")
    p.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSET",
                   help="The first revision to compare (default: @)")
    p.add_argument("-t", "--to", dest="to", default=None, metavar="REVSET",
                   help="The second revision to compare (default: @)")
    p.add_argument("paths", nargs="*", metavar="FILESETS",
                   help="Restrict the diff to these paths")
    # `interdiff` takes jj's diff-format flags, and prints the same
    # formats `diff` does.
    add_summary_flag(p)
    add_stat_flag(p)
    add_name_only_flag(p)
    add_git_flag(p)
    p.set_defaults(_handler="pyjj_cli.commands.operation.interdiff:interdiff")
