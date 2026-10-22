from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def register(git_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = git_sub.add_parser(
        "pull", help="Fetch, then fast-forward the working copy when it is safe")
    remotes = p.add_mutually_exclusive_group()
    remotes.add_argument("--remote", dest="remotes", action="append",
                         default=None, metavar="REMOTE",
                         help="Remote to fetch from (repeatable, a pattern)")
    remotes.add_argument("--all-remotes", dest="all_remotes",
                         action="store_true", help="Fetch from all remotes")
    p.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                   metavar="BRANCH", help="Branch to fetch (repeatable)")
    p.set_defaults(_handler="pyjj_cli.commands.git.pull:git_pull")
