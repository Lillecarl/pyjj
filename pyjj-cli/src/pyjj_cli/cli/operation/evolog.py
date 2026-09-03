from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("evolog", help="Show how a change has evolved over time")
    add_flags(p, [Flag.REVISIONS, Flag.LIMIT])
    p.set_defaults(_handler="pyjj_cli.commands.operation.evolog:evolog")
