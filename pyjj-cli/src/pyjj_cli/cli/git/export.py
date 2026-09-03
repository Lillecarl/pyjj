def register(git_sub) -> None:
    p = git_sub.add_parser("export", help="Update the underlying Git repo with changes made in the repo")
    p.set_defaults(_handler="pyjj_cli.commands.git.export:git_export")
