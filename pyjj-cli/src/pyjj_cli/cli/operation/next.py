def register(sub) -> None:
    p = sub.add_parser("next", help="Move the working-copy commit to the child revision")
    p.add_argument("amount", nargs="?", type=int, default=1, metavar="OFFSET",
                   help="How many revisions to move forward")
    p.add_argument("-e", "--edit", dest="edit", action="store_true", default=False,
                   help="Edit the child directly, instead of moving the working-copy commit")
    p.add_argument("-n", "--no-edit", dest="edit", action="store_false",
                   help="The inverse of --edit")
    p.set_defaults(_handler="pyjj_cli.commands.operation.next_commit:next_commit")
