"""workspace subcommand: workspace_add."""
import os
import sys
from pathlib import Path

import pyjj
from ..common import (
    _resolve_all,
    join_message_paragraphs,
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_add(args) -> int:
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
        new_ws, new_repo = ws.add_workspace(
            settings, dest, name=name, revision_ids=revision_ids,
            description=description,
            sparse_patterns=_sparse_patterns(ws, args))
        if _should_colocate(ws, settings, args):
            # After the workspace exists: the primitive supports a
            # populated destination (the `colocation enable` shape), and
            # adding first keeps the empty-destination check intact.
            new_ws.create_git_worktree(settings, dest)
            print("Created Git worktree for the new workspace.")
        print(f"Created workspace in \"{os.path.relpath(dest, os.getcwd())}\"")
        if os.sep not in args.destination:
            print(f"Warning: Workspace created inside current directory. "
                  f"If this was unintentional, delete the "
                  f"\"{args.destination}\" directory and run "
                  f"`jj workspace forget {new_ws.workspace_name}` to "
                  f"remove it.", file=sys.stderr)
        # Keep a colocated Git worktree from tracking jj's own files.
        if new_ws.is_colocated():
            try:
                Path(dest, ".jj", ".gitignore").write_text("/*\n")
            except OSError as e:
                print("Error: Failed to write .jj/.gitignore file",
                      file=sys.stderr)
                print(f"Caused by: {e}", file=sys.stderr)
                return 1
        return 0


def _should_colocate(ws, settings, args) -> bool:
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


def _sparse_patterns(ws, args):
    """What the new workspace's sparse patterns start as.

    A fresh workspace is unrestricted, so `full` -- and the `copy` of an
    unrestricted workspace -- has nothing to set, which is what `None`
    says. `empty` starts with no path at all.
    """
    choice = getattr(args, "sparse_patterns", "copy")
    if choice == "empty":
        return []
    if choice == "full":
        return None
    patterns = ws.sparse_patterns()
    # `[""]` is jj's spelling of "everything", which is where a fresh
    # workspace already starts.
    return None if not patterns or patterns == [""] else patterns
