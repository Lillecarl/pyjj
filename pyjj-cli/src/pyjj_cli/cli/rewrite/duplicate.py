from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to duplicate (default: @)")
    p.add_argument("-o", "--onto", "-d", "--destination", dest="ontos",
                   action="append", default=None, metavar="REVSETS",
                   help="Revisions to duplicate onto")
    add_flags(p, [Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.duplicate:duplicate")
