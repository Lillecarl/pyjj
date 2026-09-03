def register(sub) -> None:
    p = sub.add_parser("root", help="Show the current workspace root directory (shortcut for `jj workspace root`)")
    p.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_root:workspace_root")
