from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("revert", help="Apply the reverse of given revisions")
    p.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                   metavar="REVSETS", required=True,
                   help="Revision(s) to revert")
    add_flags(p, [Flag.ONTO, Flag.DESTINATION, Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.revert:revert")
