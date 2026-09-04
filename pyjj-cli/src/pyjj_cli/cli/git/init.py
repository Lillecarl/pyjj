def register(git_sub) -> None:
    p = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p.add_argument("destination", nargs="?", default=".", help="Destination directory")
    # jj colocates by default, so `--colocate` only matters when the
    # `git.colocate` config turns the default off.
    p.add_argument("--colocate", dest="colocate", action="store_true", default=False,
                   help="Put the git repo at the workspace root (the default)")
    p.add_argument("--no-colocate", dest="no_colocate", action="store_true", default=False,
                   help="Hide the git repo inside .jj instead")
    p.set_defaults(_handler="pyjj_cli.commands.git.init:git_init")
