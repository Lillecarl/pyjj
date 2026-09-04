def register(sub) -> None:
    p = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to abandon (default: @)")
    p.add_argument("--restore-descendants", dest="restore_descendants",
                   action="store_true", default=False,
                   help="Do not modify the content of the children of the abandoned commits")
    p.add_argument("--retain-bookmarks", dest="retain_bookmarks",
                   action="store_true", default=False,
                   help="Move bookmarks to the parent instead of deleting them")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.abandon:abandon")
