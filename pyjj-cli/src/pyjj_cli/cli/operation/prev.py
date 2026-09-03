def register(sub) -> None:
    p = sub.add_parser("prev", help="Change the working copy revision relative to the parent revision")
    p.add_argument("amount", nargs="?", type=int, default=1, metavar="OFFSET",
                   help="How many revisions to move backward")
    p.add_argument("-e", "--edit", dest="edit", action="store_true", default=False,
                   help="Edit the parent directly, instead of moving the working-copy commit")
    p.add_argument("-n", "--no-edit", dest="edit", action="store_false",
                   help="The inverse of --edit")
    p.set_defaults(_handler="pyjj_cli.commands.operation.prev_commit:prev_commit")
