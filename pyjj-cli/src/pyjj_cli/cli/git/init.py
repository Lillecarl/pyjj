def register(git_sub) -> None:
    p = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p.add_argument("destination", nargs="?", default=".", help="Destination directory")
    p.set_defaults(_handler="pyjj_cli.commands.git.init:git_init")
