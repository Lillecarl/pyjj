def register(git_sub) -> None:
    p = git_sub.add_parser("root", help="Show the underlying Git directory")
    p.set_defaults(_handler="pyjj_cli.commands.git.root:git_root")
