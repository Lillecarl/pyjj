def register(sub) -> None:
    p = sub.add_parser("redo", help="Redo a previously undone operation")
    p.set_defaults(_handler="pyjj_cli.commands.operation.redo:redo")
