def register(sub) -> None:
    p = sub.add_parser("next", help="Move the working-copy commit to the child revision")
    p.add_argument("amount", nargs="?", type=int, default=1, help="Number of revisions to move")
    p.set_defaults(_handler="pyjj_cli.commands.operation.next_commit:next_commit")
