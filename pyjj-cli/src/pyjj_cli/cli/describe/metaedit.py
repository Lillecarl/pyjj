def register(sub) -> None:
    p = sub.add_parser("metaedit",
                       help="Modify metadata of a revision without changing content")
    p.add_argument("revisions_pos", nargs="*", metavar="REVSETS",
                   help="Revisions to modify (default: @)")
    p.add_argument("-r", "--revision", dest="revisions", action="append",
                   default=None, metavar="REVSETS", help="Revisions to modify")
    p.add_argument("-m", "--message", dest="message", default=None,
                   metavar="MESSAGE", help="Update the change description")
    p.add_argument("--author", dest="author", default=None, metavar="AUTHOR",
                   help='Set the author, as "Name <email>"')
    p.add_argument("--update-author", dest="update_author", action="store_true",
                   default=False, help="Set the author to the configured user")
    p.add_argument("--update-author-timestamp", dest="update_author_timestamp",
                   action="store_true", default=False,
                   help="Set the author date to the current time")
    p.add_argument("--update-change-id", dest="update_change_id",
                   action="store_true", default=False,
                   help="Generate a new change id")
    p.set_defaults(_handler="pyjj_cli.commands.crypto.metaedit:metaedit")
