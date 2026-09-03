def register(sub) -> None:
    p = sub.add_parser("prev", help="Change the working copy revision relative to the parent revision")
    p.add_argument("amount", nargs="?", type=int, default=1, help="Number of revisions to move")
    p.set_defaults(_handler="pyjj_cli.commands.operation.prev_commit:prev_commit")
