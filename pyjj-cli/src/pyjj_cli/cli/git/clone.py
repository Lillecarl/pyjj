from ..flags import Flag, add_flags


def register(git_sub) -> None:
    p = git_sub.add_parser("clone", help="Create a new repo backed by a clone of a Git repo")
    p.add_argument("source", help="URL or path of the Git repo to clone")
    p.add_argument("destination", nargs="?", help="Target directory for the clone")
    p.add_argument("--remote", dest="remote_name", default="origin", metavar="REMOTE_NAME",
                   help="Name of the newly created remote (default: origin)")
    add_flags(p, [Flag.COLOCATE, Flag.DEPTH])
    p.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                   metavar="BRANCH", help="Branch to fetch (repeatable)")
    p.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                   metavar="TAG", help="Tag to fetch (repeatable)")
    add_flags(p, [Flag.OBJECT_HASH])
    p.set_defaults(_handler="pyjj_cli.commands.git.clone:git_clone")
