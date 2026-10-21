"""workspace subcommand: remove."""
import os
import shutil
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    read_repo,
    command,
)
from .workspace_forget import _unlink_worktree

_FORGET_HINT = ("Use `jj workspace forget` to stop tracking a workspace "
                "without deleting files.")

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_remove(args) -> int:
    if getattr(args, "ignore_working_copy", False):
        print("Error: This command must be able to update the working "
              "copy.", file=sys.stderr)
        print("Hint: Don't use --ignore-working-copy.", file=sys.stderr)
        return 1
    if getattr(args, "at_operation", None) is not None:
        print("Error: This command must be able to update the working "
              "copy.", file=sys.stderr)
        print("Hint: Don't use --at-op.", file=sys.stderr)
        return 1
    with read_repo(args) as (settings, ws, repo):
        view = repo.view()
        known = [name for name in getattr(args, "names", []) if name in view]
        for name in getattr(args, "names", []):
            if name not in view:
                print(f"Warning: No such workspace: {name}", file=sys.stderr)
        if not known:
            print("Nothing changed.", file=sys.stderr)
            return 0
        repo_path = Path(os.path.realpath(ws.repo_path))
        targets = []
        for name in known:
            recorded = ws.workspace_path(name)
            if recorded is None:
                print(f"Error: Cannot remove unreachable workspace '{name}'",
                      file=sys.stderr)
                print(f"Hint: {_FORGET_HINT}", file=sys.stderr)
                return 1
            if not os.path.exists(recorded):
                print(f"Error: Cannot access workspace '{name}' directory",
                      file=sys.stderr)
                print("Caused by: No such file or directory (os error 2)",
                      file=sys.stderr)
                print(f"Hint: {_FORGET_HINT}", file=sys.stderr)
                return 1
            canon = Path(os.path.realpath(recorded))
            if repo_path.is_relative_to(canon):
                print(f"Error: Cannot remove workspace '{name}' because it "
                      f"contains the repository", file=sys.stderr)
                return 1
            try:
                other = pyjj.Workspace.load(settings, str(canon))
            except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
                    pyjj.JjError) as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            if Path(os.path.realpath(other.repo_path)) != repo_path:
                print(f"Error: Cannot remove workspace '{name}' because it "
                      f"belongs to another repository", file=sys.stderr)
                print(f"Hint: {_FORGET_HINT}", file=sys.stderr)
                return 1
            targets.append((name, other, canon))
        # Snapshot each workspace before its directory goes away, so tracked
        # working-copy changes that were never committed survive as a commit.
        for _name, other, _canon in targets:
            try:
                other.snapshot(settings)
            except (pyjj.JjError, CommandError) as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
        joined = ", ".join(name for name, _, _ in targets)
        noun = "workspace" if len(targets) == 1 else "workspaces"
        try:
            ws.forget_workspaces(settings, [name for name, _, _ in targets],
                                 description=f"remove {noun} {joined}")
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        for name, _other, canon in targets:
            _unlink_worktree(settings, ws, name)
        for _name, _other, canon in targets:
            try:
                shutil.rmtree(canon)
            except OSError as e:
                print(f"Warning: Failed to remove workspace directory "
                      f"\"{canon}\".", file=sys.stderr)
                print(f"Error: {e}", file=sys.stderr)
            else:
                print(f"Removed workspace directory \"{canon}\".")
        return 0
