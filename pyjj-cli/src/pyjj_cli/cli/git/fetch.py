from ..flags import Flag, add_flags


def register(git_sub) -> None:
    p = git_sub.add_parser("fetch", help="Fetch from a Git remote")
    add_flags(p, [Flag.REMOTE, Flag.ALL_REMOTES, Flag.TRACKED])
    p.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                   metavar="BRANCH", help="Branch to fetch (repeatable)")
    p.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                   metavar="TAG", help="Tag to fetch (repeatable)")
    p.set_defaults(_handler="pyjj_cli.commands.git.fetch:git_fetch")
