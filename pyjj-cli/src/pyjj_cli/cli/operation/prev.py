def register(sub) -> None:
    p = sub.add_parser("prev", help="Change the working copy revision relative to the parent revision")
    # No default: `--conflict` cannot be used with an explicit offset,
    # so the command must tell "omitted" from "1".
    p.add_argument("amount", nargs="?", type=int, default=None, metavar="OFFSET",
                   help="How many revisions to move backward")
    p.add_argument("--conflict", action="store_true", default=False,
                   help="Jump to the previous conflicted ancestor")
    p.add_argument("-e", "--edit", dest="edit", action="store_true", default=False,
                   help="Edit the parent directly, instead of moving the working-copy commit")
    p.add_argument("-n", "--no-edit", dest="edit", action="store_false",
                   help="The inverse of --edit")
    p.set_defaults(_handler="pyjj_cli.commands.operation.prev_commit:prev_commit")
