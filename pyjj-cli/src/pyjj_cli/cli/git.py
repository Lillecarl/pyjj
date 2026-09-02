import argparse


def _git_help(args):
    import sys
    print("usage: pyjj git {init,clone,fetch,push,import,export,remote,root}", file=sys.stderr)
    return 2


def _git_remote_help(args):
    import sys
    print("usage: pyjj git remote {add,list,remove,rename,set-url}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_git = sub.add_parser("git", help="Git interop commands")
    p_git.set_defaults(_handler="pyjj_cli.cli.git:_git_help")
    git_sub = p_git.add_subparsers(dest="git_command")

    p_ginit = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p_ginit.add_argument("destination", nargs="?", default=".", help="Destination directory")
    p_ginit.set_defaults(_handler="pyjj_cli.commands.git.init:git_init")

    p_gclone = git_sub.add_parser("clone", help="Create a new repo backed by a clone of a Git repo")
    p_gclone.add_argument("source", help="URL or path of the Git repo to clone")
    p_gclone.add_argument("destination", nargs="?", help="Target directory for the clone")
    p_gclone.add_argument("--remote", dest="remote_name", default="origin", metavar="REMOTE_NAME",
                          help="Name of the newly created remote (default: origin)")
    p_gclone.add_argument("--colocate", dest="colocate", action="store_true", default=True,
                          help="Colocate the Jujutsu repo with the git repo (default)")
    p_gclone.add_argument("--no-colocate", dest="colocate", action="store_false",
                          help="Disable colocation")
    p_gclone.add_argument("--depth", dest="depth", type=int, default=None, metavar="DEPTH",
                          help="Create a shallow clone of the given depth")
    p_gclone.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                          metavar="BRANCH", help="Branch to fetch (repeatable)")
    p_gclone.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                          metavar="TAG", help="Tag to fetch (repeatable)")
    p_gclone.add_argument("--object-hash", dest="object_hash", default=None, metavar="OBJECT_HASH",
                          help="Object hash algorithm for the local Git repository")
    p_gclone.set_defaults(_handler="pyjj_cli.commands.git.clone:git_clone")

    p_gcolocation = git_sub.add_parser("colocation", help="Manage Jujutsu repository colocation with Git")
    p_gcolocation.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")

    colocation_sub = p_gcolocation.add_subparsers(dest="colocation_command")
    p_gcol_status = colocation_sub.add_parser("status", help="Show the current colocation status")
    p_gcol_status.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")
    p_gcol_enable = colocation_sub.add_parser("enable", help="Convert into a colocated Jujutsu/Git repository")
    p_gcol_enable.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")
    p_gcol_disable = colocation_sub.add_parser("disable", help="Convert into a non-colocated Jujutsu/Git repository")
    p_gcol_disable.set_defaults(_handler="pyjj_cli.commands.git.colocation:git_colocation")

    p_gfetch = git_sub.add_parser("fetch", help="Fetch from a Git remote")
    p_gfetch.add_argument("--remote", dest="remote", default=None, metavar="REMOTE",
                          help="The remote to fetch from")
    p_gfetch.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                          metavar="BRANCH", help="Branch to fetch (repeatable)")
    p_gfetch.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                          metavar="TAG", help="Tag to fetch (repeatable)")
    p_gfetch.add_argument("--tracked", dest="tracked", action="store_true", help="Fetch only tracked bookmarks and tags")
    p_gfetch.add_argument("--all-remotes", dest="all_remotes", action="store_true", help="Fetch from all remotes")
    p_gfetch.set_defaults(_handler="pyjj_cli.commands.git.fetch:git_fetch")

    p_gimport = git_sub.add_parser("import", help="Update repo with changes made in the underlying Git repo")
    p_gimport.set_defaults(_handler="pyjj_cli.commands.git.import_:git_import")
    p_gexport = git_sub.add_parser("export", help="Update the underlying Git repo with changes made in the repo")
    p_gexport.set_defaults(_handler="pyjj_cli.commands.git.export:git_export")

    p_gpush = git_sub.add_parser("push", help="Push to a Git remote")
    p_gpush.add_argument("--remote", dest="remote", default=None, metavar="REMOTE",
                         help="The remote to push to")
    p_gpush.add_argument("-b", "--bookmark", dest="bookmarks", action="append", default=None,
                         metavar="BOOKMARK", help="Bookmark to push (repeatable)")
    p_gpush.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                         metavar="TAG", help="Tag to push (repeatable)")
    p_gpush.add_argument("--all", dest="all_flag", action="store_true", help="Push all bookmarks and tags")
    p_gpush.add_argument("--tracked", dest="tracked", action="store_true", help="Push all tracked bookmarks and tags")
    p_gpush.add_argument("--deleted", dest="deleted", action="store_true", help="Push all deleted bookmarks and tags")
    p_gpush.add_argument("--allow-empty-description", dest="allow_empty", action="store_true", help="Allow pushing commits with empty descriptions")
    p_gpush.add_argument("--allow-private", dest="allow_private", action="store_true", help="Allow pushing commits that are private")
    p_gpush.add_argument("--allow-conflicts", dest="allow_conflicts", action="store_true", help="Allow pushing commits that contain conflicts")
    p_gpush.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show what would be pushed without actually pushing")
    p_gpush.add_argument("-c", "--change", dest="changes", action="append", default=None,
                         metavar="REVSETS", help="Push this commit by creating a bookmark")
    p_gpush.add_argument("--named", dest="named", action="append", default=None,
                         metavar="NAME@REV", help="Push a revision as a named bookmark")
    p_gpush.set_defaults(_handler="pyjj_cli.commands.git.push:git_push")

    p_gremote = git_sub.add_parser("remote", help="Manage Git remotes")
    p_gremote.set_defaults(_handler="pyjj_cli.cli.git:_git_remote_help")
    remote_sub = p_gremote.add_subparsers(dest="remote_command")
    p_gr_list = remote_sub.add_parser("list", help="List Git remotes")
    p_gr_list.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_gr_add = remote_sub.add_parser("add", help="Add a Git remote")
    p_gr_add.add_argument("name", help="Remote name")
    p_gr_add.add_argument("url", help="Remote URL")
    p_gr_add.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_gr_remove = remote_sub.add_parser("remove", help="Remove a Git remote")
    p_gr_remove.add_argument("name", help="Remote name")
    p_gr_remove.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_gr_rename = remote_sub.add_parser("rename", help="Rename a Git remote")
    p_gr_rename.add_argument("old", help="Old remote name")
    p_gr_rename.add_argument("new", help="New remote name")
    p_gr_rename.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")
    p_gr_set_url = remote_sub.add_parser("set-url", help="Set the URL of a Git remote")
    p_gr_set_url.add_argument("name", help="Remote name")
    p_gr_set_url.add_argument("--url", dest="url", default=None, help="New URL")
    p_gr_set_url.add_argument("--push-url", dest="push_url", default=None, help="New push URL")
    p_gr_set_url.set_defaults(_handler="pyjj_cli.commands.git.remote:git_remote")

    p_groot = git_sub.add_parser("root", help="Show the underlying Git directory")
    p_groot.set_defaults(_handler="pyjj_cli.commands.git.root:git_root")
