def register(git_sub) -> None:
    p = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p.add_argument("destination", nargs="?", default=".", help="Destination directory")
    # jj colocates by default, so `--colocate` only matters when the
    # `git.colocate` config turns the default off.
    p.add_argument("--colocate", dest="colocate", action="store_true", default=False,
                   help="Put the git repo at the workspace root (the default)")
    p.add_argument("--no-colocate", dest="no_colocate", action="store_true", default=False,
                   help="Hide the git repo inside .jj instead")
    p.add_argument("--git-repo", dest="git_repo", default=None, metavar="GIT_REPO",
                   help="Use an existing git repository as the backing git repo")
    p.add_argument("--object-hash", dest="object_hash", default=None,
                   choices=("sha1", "sha256"), metavar="OBJECT_HASH",
                   help="Object hash algorithm for the new Git repository")
    p.set_defaults(_handler="pyjj_cli.commands.git.init:git_init")
