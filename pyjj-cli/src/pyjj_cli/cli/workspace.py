from __future__ import annotations

import argparse
import re
from datetime import timedelta
from typing import Final

from .flags import Flag, add_flags

_UNIT_SECONDS: Final = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_PART: Final = re.compile(r"(\d+)([smhdw])")


def _parse_duration(text: str) -> timedelta:
    """`30d`, `2w`, `1w3d12h`: whole numbers, each with one of s m h d w."""
    parts: list[tuple[str, str]] = _DURATION_PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise argparse.ArgumentTypeError(
            f"invalid duration {text!r} (expected e.g. 30d, 2w, 1d12h)")
    return timedelta(seconds=sum(int(n) * _UNIT_SECONDS[u] for n, u in parts))


def _workspace_help(args: argparse.Namespace):
    import sys
    print("usage: pyjj workspace {add,clean,forget,list,remove,rename,root,update-stale}", file=sys.stderr)
    return 2


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_ws = sub.add_parser("workspace", help="Commands for working with workspaces")
    p_ws.set_defaults(_handler="pyjj_cli.cli.workspace:_workspace_help")
    ws_sub = p_ws.add_subparsers(dest="workspace_command")
    p_ws_add = ws_sub.add_parser("add", help="Add a workspace")
    p_ws_add.add_argument("destination", help="Where to create the new workspace")
    p_ws_add.add_argument("--name", dest="name", default=None, help="A name for the workspace")
    add_flags(p_ws_add, [Flag.REVISION_APPEND, Flag.MESSAGE_APPEND])
    colocate_group = p_ws_add.add_mutually_exclusive_group()
    colocate_group.add_argument("--colocate", dest="colocate",
                                action="store_true",
                                help="Create a corresponding Git worktree "
                                     "for this workspace")
    colocate_group.add_argument("--no-colocate", dest="no_colocate",
                                action="store_true",
                                help="Do not create a Git worktree for this "
                                     "workspace")
    p_ws_add.add_argument("--sparse-patterns", dest="sparse_patterns",
                          choices=("copy", "full", "empty"), default="copy",
                          help="What the new workspace's sparse patterns "
                               "start as (default: copy)")
    p_ws_add.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_add:workspace_add")
    p_ws_forget = ws_sub.add_parser("forget", help="Stop tracking a workspace")
    p_ws_forget.add_argument("names", nargs="+", help="Workspaces to forget")
    p_ws_forget.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_forget:workspace_forget")
    p_ws_list = ws_sub.add_parser("list", help="List workspaces")
    add_flags(p_ws_list, [Flag.TEMPLATE])
    p_ws_list.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_list:workspace_list")
    p_ws_rename = ws_sub.add_parser("rename", help="Renames the current workspace")
    p_ws_rename.add_argument("new_name", help="New workspace name")
    p_ws_rename.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_rename:workspace_rename")
    p_ws_root = ws_sub.add_parser("root", help="Show the workspace root directory")
    p_ws_root.add_argument("--name", default=None, metavar="NAME",
                           help="Name of the workspace (defaults to current)")
    p_ws_root.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_root:workspace_root")
    p_ws_update = ws_sub.add_parser("update-stale", help="Update a workspace that has become stale")
    p_ws_update.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_update_stale:workspace_update_stale")
    p_ws_remove = ws_sub.add_parser("remove", help="Remove a workspace and its files from disk")
    p_ws_remove.add_argument("names", nargs="+", help="Workspaces to remove")
    p_ws_remove.set_defaults(_handler="pyjj_cli.commands.workspace.remove:workspace_remove")
    p_ws_clean = ws_sub.add_parser(
        "clean",
        help="Remove every workspace whose work is all in trunk()",
        description="Remove and forget every workspace whose work is in "
                    "trunk(): its working-copy commit has no ancestors "
                    "outside trunk() (ignoring an empty undescribed "
                    "working-copy commit), or trunk() already holds all its "
                    "changes as other commits, as after a squash-merge. "
                    "Workspaces whose directory is gone are forgotten. A "
                    "workspace with files changed on disk is always kept, "
                    "stale or not. Nothing is written until --force; without "
                    "it the command only lists, like git clean. A workspace "
                    "that a process is using (working directory, executable "
                    "or open file, read from /proc and checked again just "
                    "before deleting) is never removed; without /proc nothing "
                    "is. The current workspace and the one holding the "
                    "repository are never removed. pyjj's own; jj has no such "
                    "command.")
    p_ws_clean.add_argument("-f", "--force", dest="force", action="store_true",
                            help="Remove the workspaces instead of listing them")
    p_ws_clean.add_argument(
        "--grace", dest="grace", metavar="DURATION", type=_parse_duration,
        default=timedelta(hours=1),
        help="Keep workspaces whose working-copy commit changed more recently "
             "than DURATION (default 1h; 0s turns it off). Covers a workspace "
             "created for work no process has started in yet")
    p_ws_clean.add_argument("--format", choices=["text", "json"], default="text",
                            help="json prints every workspace with its action "
                                 "and reason as one object on stdout")
    p_ws_clean.add_argument(
        "--older-than", dest="older_than", metavar="DURATION",
        type=_parse_duration, default=None,
        help="Also remove workspaces whose working-copy commit was last "
             "rewritten longer ago than DURATION (30d, 2w, 1d12h), merged "
             "or not. Their commits stay in the repository; only the "
             "directory goes")
    p_ws_clean.set_defaults(_handler="pyjj_cli.commands.workspace.clean:workspace_clean")
