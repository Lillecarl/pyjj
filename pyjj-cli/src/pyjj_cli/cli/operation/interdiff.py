def register(sub) -> None:
    p = sub.add_parser("interdiff", help="Show differences between the diffs of two revisions")
    p.set_defaults(_handler="pyjj_cli.commands.operation.interdiff:interdiff")
