from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
# cli/git package — one module per subcommand, mirroring commands/git/.


def _git_help(args: argparse.Namespace):
    import sys
    print("usage: pyjj git {init,clone,fetch,pull,push,import,export,remote,root}", file=sys.stderr)
    return 2


def _git_remote_help(args: argparse.Namespace):
    import sys
    print("usage: pyjj git remote {add,list,remove,rename,set-url}", file=sys.stderr)
    return 2


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    from . import clone, colocation, export, fetch, git_import, init, pull, push, remote, root

    p_git = sub.add_parser("git", help="Git interop commands")
    p_git.set_defaults(_handler="pyjj_cli.cli.git:_git_help")
    git_sub = p_git.add_subparsers(dest="git_command")

    init.register(git_sub)
    clone.register(git_sub)
    colocation.register(git_sub)
    fetch.register(git_sub)
    pull.register(git_sub)
    git_import.register(git_sub)
    export.register(git_sub)
    push.register(git_sub)
    remote.register(git_sub)
    root.register(git_sub)
