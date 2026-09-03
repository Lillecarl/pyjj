def register(sub) -> None:
    p = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                   help="Parent revisions (default: @)")
    p.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                   help="Description of the new change")
    p.set_defaults(_handler="pyjj_cli.commands.describe.new:new")
