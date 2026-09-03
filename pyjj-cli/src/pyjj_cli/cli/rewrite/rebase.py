from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("rebase", help="Move revisions to a different parent")
    add_flags(p, [Flag.REVISION_APPEND, Flag.SOURCE, Flag.BRANCH, Flag.DESTINATION, Flag.ONTO, Flag.INSERT_AFTER, Flag.INSERT_BEFORE])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.rebase:rebase")
