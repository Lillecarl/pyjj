from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("metaedit", help="Modify metadata of a revision without changing content")
    p.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to modify")
    add_flags(p, [Flag.AUTHOR, Flag.COMMITTER])
    p.set_defaults(_handler="pyjj_cli.commands.crypto.metaedit:metaedit")
