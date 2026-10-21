"""workspace subcommand: workspace_add."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _resolve_all,
    command,
    join_message_paragraphs,
    maybe_add_gitignore,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_add(args: argparse.Namespace) -> int:
    """`jj workspace add DESTINATION` — a second working copy on one repo."""
    with read_repo(args) as (settings, ws, repo):
        dest = str(Path(args.destination).resolve())
        revs = getattr(args, "revisions", None)
        revision_ids = None
        if revs:
            commits = _resolve_all(repo, settings, revs)
            revision_ids = [c.id for c in commits]
        name = getattr(args, "name", None)
        paragraphs = getattr(args, "messages", None)
        description = join_message_paragraphs(paragraphs) if paragraphs else None
        colocate = _should_colocate(ws, settings, args)
        new_ws, new_repo = ws.add_workspace(
            settings, dest, name=name, revision_ids=revision_ids,
            description=description,
            sparse_patterns=_sparse_patterns(ws, args),
            colocate=colocate)
        if colocate:
            print("Created Git worktree for the new workspace.")
        print(f"Created workspace in \"{os.path.relpath(dest, os.getcwd())}\"")
        if os.sep not in args.destination:
            print(f"Warning: Workspace created inside current directory. "
                  f"If this was unintentional, delete the "
                  f"\"{args.destination}\" directory and run "
                  f"`jj workspace forget {new_ws.workspace_name}` to "
                  f"remove it.", file=sys.stderr)
        return maybe_add_gitignore(new_ws)


def _should_colocate(ws: pyjj.Workspace, settings: pyjj.UserSettings, args: argparse.Namespace) -> bool:
    """Whether the new workspace gets a Git worktree, mirroring
    `cli/src/commands/workspace/add.rs`: `--colocate` forces one,
    `--no-colocate` refuses one, and otherwise a worktree is created
    when the current workspace is itself colocated and `git.colocate`
    (which defaults to true) says so."""
    if getattr(args, "colocate", False):
        return True
    if getattr(args, "no_colocate", False):
        return False
    if not ws.is_colocated():
        return False
    # `git.colocate` defaults to true when unset.
    return settings.get_bool("git.colocate") != False


def _sparse_patterns(ws: pyjj.Workspace, args: argparse.Namespace) -> list[str] | None:
    """What the new workspace's sparse patterns start as. `None` is
    `copy`, the binding's default as it is jj's; `[""]` is everything."""
    choice = getattr(args, "sparse_patterns", "copy")
    if choice == "empty":
        return []
    if choice == "full":
        return [""]
    return None
