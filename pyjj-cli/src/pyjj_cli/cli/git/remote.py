def register(git_sub) -> None:
    p = git_sub.add_parser("remote", help="Manage Git remotes")
    p.set_defaults(_handler="pyjj_cli.cli.git:_git_remote_help")
    remote_sub = p.add_subparsers(dest="remote_command")
    p_list = remote_sub.add_parser("list", help="List Git remotes")
    p_list.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_add = remote_sub.add_parser("add", help="Add a Git remote")
    p_add.add_argument("name", help="Remote name")
    p_add.add_argument("url", help="Remote URL")
    p_add.add_argument("--fetch-tags", dest="fetch_tags", default=None,
                       metavar="FETCH_TAGS",
                       choices=("all", "included", "none"),
                       help="Configure when to fetch tags")
    p_add.add_argument("--push-url", dest="push_url", default=None,
                       metavar="PUSH_URL", help="The URL used for push")
    p_add.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_remove = remote_sub.add_parser("remove", help="Remove a Git remote")
    p_remove.add_argument("name", help="Remote name")
    p_remove.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_rename = remote_sub.add_parser("rename", help="Rename a Git remote")
    p_rename.add_argument("old", help="Old remote name")
    p_rename.add_argument("new", help="New remote name")
    p_rename.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_set_url = remote_sub.add_parser("set-url", help="Set the URL of a Git remote")
    p_set_url.add_argument("name", help="Remote name")
    # A bare URL is the short form of --fetch.
    p_set_url.add_argument("url", nargs="?", default=None,
                           help="The URL or path to fetch from")
    p_set_url.add_argument("--fetch", dest="fetch", default=None,
                           metavar="FETCH",
                           help="The URL or path to fetch from")
    p_set_url.add_argument("--push", dest="push", default=None,
                           metavar="PUSH", help="The URL or path to push to")
    p_set_url.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
