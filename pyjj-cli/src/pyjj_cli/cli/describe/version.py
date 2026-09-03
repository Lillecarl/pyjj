def register(sub) -> None:
    p = sub.add_parser("version", help="Show version information")
    p.set_defaults(_handler="pyjj_cli.commands.crypto.version:version")
