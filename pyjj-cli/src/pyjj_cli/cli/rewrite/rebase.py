from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("rebase", help="Move revisions to a different parent")
    # jj gives rebase's `-r` a hidden `--revisions` alias, and no other
    # command that takes `-r` has one, so it is spelled out here.
    p.add_argument("-r", "--revision", "--revisions", dest="revisions",
                   action="append", default=None, metavar="REVSETS",
                   help="Revision to operate on (can be repeated)")
    p.add_argument("--skip-emptied", dest="skip_emptied", action="store_true",
                   default=False,
                   help="Abandon a commit the rebase newly empties")
    p.add_argument("--keep-divergent", dest="keep_divergent",
                   action="store_true", default=False,
                   help="Keep a divergent commit the destination already holds")
    p.add_argument("--simplify-parents", dest="simplify_parents",
                   action="store_true", default=False,
                   help="Drop a parent that is an ancestor of another parent")
    add_flags(p, [Flag.SOURCE, Flag.BRANCH, Flag.DESTINATION, Flag.ONTO, Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.rebase:rebase")
