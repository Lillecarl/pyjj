def register(git_sub) -> None:
    p = git_sub.add_parser("import", help="Update repo with changes made in the underlying Git repo")
    p.set_defaults(_handler="pyjj_cli.commands.git.import_:git_import")
