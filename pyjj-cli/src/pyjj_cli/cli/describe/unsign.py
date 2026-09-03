from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("unsign", help="Drop a cryptographic signature")
    add_flags(p, [Flag.REVISION_APPEND])
    p.set_defaults(_handler="pyjj_cli.commands.crypto.unsign:unsign")
