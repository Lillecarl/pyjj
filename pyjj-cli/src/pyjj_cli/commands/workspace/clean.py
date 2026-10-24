"""workspace subcommand: clean. pyjj's own; jj has no such command."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import pyjj

from ..common import _format_timestamp, _workspace_path, command, settings_for
from .remove import (
    Refused,
    forget_and_delete,
    holds_repository,
    refuse_unwritable_working_copy,
    removal_target,
    report_deleted,
)

if TYPE_CHECKING:
    import argparse
    from datetime import timedelta

class Action(StrEnum):
    REMOVE = "remove"
    FORGET = "forget"
    KEEP = "keep"


@dataclass(frozen=True, slots=True)
class Decision:
    name: str
    path: Path | None
    action: Action
    reason: str
    failed: bool = False

    def as_json(self) -> dict[str, str | None]:
        return {"name": self.name, "path": None if self.path is None else str(self.path),
                "action": self.action, "reason": self.reason}


def unmerged_revset(name: str) -> str:
    """Commits workspace `name` holds that `trunk()` lacks.

    The working-copy commit itself is left out while it is empty and
    undescribed: that is the state `workspace add` and `new` leave, and
    it carries nothing to lose.
    """
    wc = f"{json.dumps(name)}@"
    return f'(::{wc} ~ ::trunk()) ~ ({wc} & empty() & description(exact:""))'


def changes_in_trunk(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, name: str) -> bool:
    """Whether trunk() holds every change the workspace makes since it
    forked, as other commits: a squash- or rebase-merge. One tree merge,
    costing the paths the work changed, however many commits it spans."""
    trunk = repo.resolve_single(settings, "trunk()")
    if not trunk.parent_ids:
        return False
    wc = f"{json.dumps(name)}@"
    forks = repo.revset(settings, f"heads(::{wc} & ::trunk())")
    if len(forks) != 1:
        return False
    tip = repo.resolve_single(settings, wc)
    return repo.contains_changes(trunk, forks[0], tip)


def decide(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, ws: pyjj.Workspace,
           name: str, cutoff_millis: int | None, grace_millis: int) -> Decision:
    """What `clean` does with workspace `name`. Writes nothing."""
    if name == ws.workspace_name:
        return Decision(name, Path(ws.workspace_root), Action.KEEP, "current workspace")
    recorded = ws.workspace_path(name)
    if recorded is None:
        # Not the same as a missing directory: the store cannot say where
        # it is, and `workspace remove` refuses it for that reason.
        return Decision(name, None, Action.KEEP,
                        "no recorded path; use `workspace forget`", failed=True)
    if not os.path.exists(recorded):
        return Decision(name, Path(recorded), Action.FORGET, "directory missing")
    path = Path(os.path.realpath(recorded))
    if holds_repository(ws, name):
        return Decision(name, path, Action.KEEP, "holds the repository")
    try:
        other = removal_target(settings, ws, name).workspace
        if other.has_unrecorded_changes(settings):
            return Decision(name, path, Action.KEEP, "unrecorded changes")
    except (Refused, pyjj.JjError) as e:
        return Decision(name, path, Action.KEEP, getattr(e, "message", str(e)), failed=True)
    stamp = repo.get_commit(pyjj.CommitId(repo.view()[name])).committer.timestamp
    if stamp.millis_since_epoch > grace_millis:
        return Decision(name, path, Action.KEEP,
                        f"active since {_format_timestamp(stamp)}, within --grace")
    unmerged = repo.revset(settings, unmerged_revset(name))
    if not unmerged:
        return Decision(name, path, Action.REMOVE, "merged")
    if changes_in_trunk(repo, settings, name):
        return Decision(name, path, Action.REMOVE, "changes in trunk")
    if cutoff_millis is not None and stamp.millis_since_epoch < cutoff_millis:
        return Decision(name, path, Action.REMOVE, f"idle since {_format_timestamp(stamp)}")
    return Decision(name, path, Action.KEEP, "unmerged")


@dataclass(frozen=True, slots=True)
class Process:
    pid: int
    command: str
    paths: tuple[Path, ...]


def processes() -> list[Process] | None:
    """Every readable process with the paths it is using: its working
    directory, its executable and its open files. None where `/proc` is
    missing, since then nothing can be ruled out. Processes of other
    users are unreadable and so invisible here."""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    found: list[Process] = []
    me = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        links = [entry / "cwd", entry / "exe"]
        with contextlib.suppress(OSError):
            links.extend((entry / "fd").iterdir())
        paths: list[Path] = []
        for link in links:
            with contextlib.suppress(OSError):  # exited, or not ours
                paths.append(Path(os.readlink(link)))
        if paths:
            command = ""
            with contextlib.suppress(OSError):
                command = (entry / "comm").read_text().strip()
            found.append(Process(int(entry.name), command, tuple(paths)))
    return found


def user_of(root: Path, procs: list[Process]) -> Process | None:
    for process in procs:
        if any(path == root or root in path.parents for path in process.paths):
            return process
    return None


def keep_in_use(decisions: list[Decision], procs: list[Process] | None) -> list[Decision]:
    """`decisions` with every removal of a directory some process uses
    turned into a keep. Forgetting a missing directory is never blocked."""
    guarded: list[Decision] = []
    for d in decisions:
        if d.action is not Action.REMOVE or d.path is None:
            guarded.append(d)
        elif procs is None:
            guarded.append(Decision(d.name, d.path, Action.KEEP,
                                    "cannot tell whether it is in use (no /proc)", failed=True))
        elif (user := user_of(d.path, procs)) is not None:
            guarded.append(Decision(d.name, d.path, Action.KEEP,
                                    f"in use by pid {user.pid} ({user.command})"))
        else:
            guarded.append(d)
    return guarded


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_clean(args: argparse.Namespace) -> int:
    if (rc := refuse_unwritable_working_copy(args)) is not None:
        return rc
    settings = settings_for(args)
    # No snapshot: the current workspace is never a candidate, and
    # nothing is written until --force.
    ws = pyjj.Workspace.load(settings, _workspace_path(args))
    repo = ws.load_at_head()
    now = time.time()
    older_than: timedelta | None = getattr(args, "older_than", None)
    cutoff = None if older_than is None else int((now - older_than.total_seconds()) * 1000)
    grace: timedelta = args.grace
    grace_millis = int((now - grace.total_seconds()) * 1000)
    decisions = [decide(repo, settings, ws, name, cutoff, grace_millis)
                 for name in sorted(repo.view())]
    force = getattr(args, "force", False)
    # Twice under --force: a process may have entered since the first scan.
    for _ in range(2 if force else 1):
        if any(d.action is Action.REMOVE for d in decisions):
            decisions = keep_in_use(decisions, processes())
    chosen = [d for d in decisions if d.action is not Action.KEEP]
    as_json = getattr(args, "format", "text") == "json"
    deleted: dict[Path, OSError | None] = {}
    if force and chosen:
        deleted = forget_and_delete(
            settings, ws, [d.name for d in chosen],
            [d.path for d in chosen if d.action is Action.REMOVE and d.path is not None])
    if as_json:
        print(json.dumps({
            "applied": force and bool(chosen),
            "workspaces": [d.as_json() for d in decisions],
            "failed": {str(root): str(error) for root, error in deleted.items() if error},
        }))
        return 0
    for d in decisions:
        if d.failed:
            print(f"Warning: Skipping workspace '{d.name}': {d.reason}", file=sys.stderr)
    if not chosen:
        print("Nothing changed.", file=sys.stderr)
        return 0
    if not force:
        for d in chosen:
            where = "" if d.path is None else f" \"{d.path}\""
            print(f"Would {d.action} workspace {d.name}{where} ({d.reason}).")
        print("Hint: Pass --force to remove them.", file=sys.stderr)
        return 0
    for d in chosen:
        if d.action is Action.FORGET:
            print(f"Forgot workspace {d.name} ({d.reason}).")
    report_deleted(deleted)
    return 0
