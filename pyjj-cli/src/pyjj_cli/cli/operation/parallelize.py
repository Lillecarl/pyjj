def register(sub) -> None:
    p = sub.add_parser("parallelize", help="Parallelize revisions by making them siblings")
    p.set_defaults(_handler="pyjj_cli.commands.operation.parallelize:parallelize")
