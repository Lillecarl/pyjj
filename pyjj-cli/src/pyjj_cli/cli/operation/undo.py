def register(sub) -> None:
    p = sub.add_parser("undo", help="Undo the last operation")
    p.add_argument("--allow-cross-workspace", dest="allow_cross_workspace",
                   action="store_true",
                   help="Allow undoing an operation that was performed in "
                        "another workspace")
    p.set_defaults(_handler="pyjj_cli.commands.operation.undo:undo")
