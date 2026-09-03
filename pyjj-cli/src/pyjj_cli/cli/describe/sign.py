from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("sign", help="Cryptographically sign a revision")
    add_flags(p, [Flag.REVISION_APPEND, Flag.KEY])
    p.set_defaults(_handler="pyjj_cli.commands.crypto.sign:sign")
