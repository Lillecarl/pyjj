from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("squash", help="Move changes from a revision into another")
    p.add_argument("-r", "--revision", dest="revision", default=None,
                   metavar="REVSET",
                   help="Revision to squash into its parent (default: @)")
    p.add_argument("-f", "--from", dest="from_", action="append", default=None,
                   metavar="REVSETS", help="Revision(s) to squash from (default: @)")
    # The experimental placement UI. jj gives it one option with four
    # spellings, so all four land in the same list.
    p.add_argument("-o", "--onto", "-d", "--destination", dest="ontos",
                   action="append", default=None, metavar="REVSETS",
                   help="(Experimental) Parent(s) for the new commit")
    p.add_argument("-k", "--keep-emptied", dest="keep_emptied",
                   action="store_true", default=False,
                   help="Leave the source revision behind when it ends up empty")
    add_flags(p, [Flag.INTO, Flag.USE_DEST_MESSAGE, Flag.MESSAGE, Flag.EDITOR,
                  Flag.TOOL, Flag.INSERT_AFTER, Flag.INSERT_BEFORE,
                  Flag.FILESETS])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.squash:squash")
