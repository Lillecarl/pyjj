from ..flags import Flag, add_flags


def register(git_sub) -> None:
    p = git_sub.add_parser("fetch", help="Fetch from a Git remote")
    # jj takes `--remote` more than once here, and reads each one as a
    # name pattern. Every other command with the flag takes one remote,
    # so this spelling is declared here rather than shared.
    remotes = p.add_mutually_exclusive_group()
    remotes.add_argument("--remote", dest="remotes", action="append",
                         default=None, metavar="REMOTE",
                         help="Remote to fetch from (repeatable, a pattern)")
    remotes.add_argument("--all-remotes", dest="all_remotes",
                         action="store_true", help="Fetch from all remotes")
    add_flags(p, [Flag.TRACKED])
    p.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                   metavar="BRANCH", help="Branch to fetch (repeatable)")
    p.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                   metavar="TAG", help="Tag to fetch (repeatable)")
    p.set_defaults(_handler="pyjj_cli.commands.git.fetch:git_fetch")
