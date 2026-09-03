def register(git_sub) -> None:
    p = git_sub.add_parser("colocation", help="Manage Jujutsu repository colocation with Git")
    p.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")

    colocation_sub = p.add_subparsers(dest="colocation_command")
    p_status = colocation_sub.add_parser("status", help="Show the current colocation status")
    p_status.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")
    p_enable = colocation_sub.add_parser("enable", help="Convert into a colocated Jujutsu/Git repository")
    p_enable.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")
    p_disable = colocation_sub.add_parser("disable", help="Convert into a non-colocated Jujutsu/Git repository")
    p_disable.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")
