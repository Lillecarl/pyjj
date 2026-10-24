"""workspace subcommand: remove."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    CommandError,
    command,
    read_repo,
)
from .workspace_forget import _unlink_worktree

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

_FORGET_HINT = ("Use `jj workspace forget` to stop tracking a workspace "
                "without deleting files.")


class Refused(Exception):
    """A workspace that `remove` must not delete, with jj's wording."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    workspace: pyjj.Workspace
    root: Path


def holds_repository(ws: pyjj.Workspace, name: str) -> bool:
    recorded = ws.workspace_path(name)
    if recorded is None:
        return False
    return Path(os.path.realpath(ws.repo_path)).is_relative_to(
        Path(os.path.realpath(recorded)))


def removal_target(settings: pyjj.UserSettings, ws: pyjj.Workspace, name: str) -> Target:
    """Load workspace `name` for removal, or raise `Refused`."""
    repo_path = Path(os.path.realpath(ws.repo_path))
    recorded = ws.workspace_path(name)
    if recorded is None:
        raise Refused(f"Cannot remove unreachable workspace '{name}'", _FORGET_HINT)
    if not os.path.exists(recorded):
        raise Refused(f"Cannot access workspace '{name}' directory\n"
                      "Caused by: No such file or directory (os error 2)",
                      _FORGET_HINT)
    canon = Path(os.path.realpath(recorded))
    if holds_repository(ws, name):
        raise Refused(f"Cannot remove workspace '{name}' because it "
                      "contains the repository")
    try:
        other = pyjj.Workspace.load(settings, str(canon))
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        raise Refused(getattr(e, "message", str(e))) from e
    if Path(os.path.realpath(other.repo_path)) != repo_path:
        raise Refused(f"Cannot remove workspace '{name}' because it "
                      "belongs to another repository", _FORGET_HINT)
    return Target(name, other, canon)


def snapshot_targets(settings: pyjj.UserSettings, targets: Sequence[Target]) -> None:
    """Snapshot each workspace before its directory goes away, so tracked
    working-copy changes that were never committed survive as a commit."""
    for target in targets:
        target.workspace.snapshot(settings)


def forget_and_delete(settings: pyjj.UserSettings, ws: pyjj.Workspace,
                      names: Sequence[str], roots: Sequence[Path]) -> dict[Path, OSError | None]:
    """Forget `names` in one operation, then delete `roots`.

    The description starts with `remove workspace`, which is what `undo`
    keys its directory-not-restored warning on. Returns each root with
    the error that kept it, if any.
    """
    noun = "workspace" if len(names) == 1 else "workspaces"
    ws.forget_workspaces(settings, list(names),
                         description=f"remove {noun} {', '.join(names)}")
    for name in names:
        _unlink_worktree(settings, ws, name)
    deleted: dict[Path, OSError | None] = {}
    for root in roots:
        try:
            shutil.rmtree(root)
        except OSError as e:
            deleted[root] = e
        else:
            deleted[root] = None
    return deleted


def report_deleted(deleted: dict[Path, OSError | None]) -> None:
    for root, error in deleted.items():
        if error is None:
            print(f"Removed workspace directory \"{root}\".")
        else:
            print(f"Warning: Failed to remove workspace directory "
                  f"\"{root}\".", file=sys.stderr)
            print(f"Error: {error}", file=sys.stderr)


def remove_targets(settings: pyjj.UserSettings, ws: pyjj.Workspace, targets: Sequence[Target]) -> None:
    report_deleted(forget_and_delete(settings, ws, [target.name for target in targets],
                                     [target.root for target in targets]))


def refuse_unwritable_working_copy(args: argparse.Namespace) -> int | None:
    if getattr(args, "ignore_working_copy", False):
        hint = "Don't use --ignore-working-copy."
    elif getattr(args, "at_operation", None) is not None:
        hint = "Don't use --at-op."
    else:
        return None
    print("Error: This command must be able to update the working "
          "copy.", file=sys.stderr)
    print(f"Hint: {hint}", file=sys.stderr)
    return 1


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_remove(args: argparse.Namespace) -> int:
    if (rc := refuse_unwritable_working_copy(args)) is not None:
        return rc
    with read_repo(args) as (settings, ws, repo):
        view = repo.view()
        known = [name for name in getattr(args, "names", []) if name in view]
        for name in getattr(args, "names", []):
            if name not in view:
                print(f"Warning: No such workspace: {name}", file=sys.stderr)
        if not known:
            print("Nothing changed.", file=sys.stderr)
            return 0
        try:
            targets = [removal_target(settings, ws, name) for name in known]
        except Refused as e:
            print(f"Error: {e.message}", file=sys.stderr)
            if e.hint is not None:
                print(f"Hint: {e.hint}", file=sys.stderr)
            return 1
        try:
            snapshot_targets(settings, targets)
            remove_targets(settings, ws, targets)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        return 0
