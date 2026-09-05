from ..flags import Flag, add_flags


def register(git_sub) -> None:
    p = git_sub.add_parser("push", help="Push to a Git remote")
    add_flags(p, [Flag.REMOTE, Flag.BOOKMARK, Flag.TAG, Flag.ALL, Flag.TRACKED, Flag.DELETED, Flag.ALLOW_EMPTY, Flag.ALLOW_PRIVATE, Flag.ALLOW_CONFLICTS, Flag.DRY_RUN, Flag.CHANGE, Flag.NAMED])
    # jj spells push's `-r` in the plural and takes it more than once.
    p.add_argument("-r", "--revision", dest="revisions", action="append",
                   default=None, metavar="REVSETS",
                   help="Push bookmarks pointing to these commits (repeatable)")
    p.add_argument("-o", "--option", dest="push_options", action="append",
                   default=None, metavar="OPTION", help="Git push options")
    p.set_defaults(_handler="pyjj_cli.commands.git.push:git_push")
