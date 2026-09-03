def register(sub) -> None:
    p = sub.add_parser("undo", help="Undo the last operation")
    p.set_defaults(_handler="pyjj_cli.commands.operation.undo:undo")
