"""git subcommand: git_colocation."""
import errno
import os
import subprocess
import sys
from pathlib import Path

import pyjj
from ..common import (
    _finish,
    _start_transaction,
    command,
    maybe_add_gitignore,
    read_repo,
)
from ..workspace.workspace_forget import _unlink_worktree


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_colocation(args) -> int:
    """`jj git colocation` — manage colocation status."""
    sub = getattr(args, "colocation_command", None)
    handler = {"status": _status, "enable": _enable,
               "disable": _disable}.get(sub)
    if handler is None:
        print("usage: pyjj git colocation {status,enable,disable}",
              file=sys.stderr)
        return 2
    with read_repo(args) as (settings, ws, repo):
        return handler(settings, ws, repo)


def _status(settings, ws, repo) -> int:
    # The faithful detector, not the mere presence of a `.git` entry (an
    # unrelated repo's file there would lie).
    is_colocated = ws.is_colocated()
    state = "currently" if is_colocated else "currently not"
    print(f"Workspace '{ws.workspace_name}' is {state} colocated with Git.")
    head = ", ".join(h if h is not None else "(none)"
                     for h in repo.git_head(ws.workspace_name))
    print(f"Last imported/exported Git HEAD: {head}")
    if is_colocated:
        print("Hint: To disable colocation, run: `jj git colocation disable`",
              file=sys.stderr)
    elif (not _is_child_workspace(ws)
          and not Path(ws.repo_path, "store", "git").exists()):
        print("Hint: Colocation cannot be enabled because the workspace is "
              "backed by an external Git repository.", file=sys.stderr)
    else:
        print("Hint: To enable colocation, run: `jj git colocation enable`",
              file=sys.stderr)
    return 0


def _enable(settings, ws, repo) -> int:
    if ws.is_colocated():
        print("Workspace is already colocated with Git.", file=sys.stderr)
        return 0
    if ws.workspace_name not in repo.view():
        print("Error: This command requires a working copy", file=sys.stderr)
        return 1
    root = Path(ws.workspace_root)
    if _is_child_workspace(ws):
        ws.create_git_worktree(settings, str(root))
    else:
        store = Path(ws.repo_path, "store")
        try:
            os.rename(store / "git", root / ".git")
        except OSError as e:
            if e.errno in (errno.EEXIST, errno.ENOTEMPTY):
                return _error("A .git directory already exists in the "
                              "workspace root. Cannot colocate.")
            if e.errno == errno.ENOENT:
                # An external Git repository (`jj git init --git-repo`)
                # is not jj's to move.
                target = (store / (store / "git_target").read_text()).resolve()
                return _error("Cannot colocate a workspace backed by an "
                              f"external Git repository at {target}")
            return _error("Failed to move Git repository from "
                          ".jj/repo/store/git to workspace root directory.", e)
        (store / "git_target").write_text("../../../.git")
        _set_bare(root / ".git", False)
    new_ws, new_repo = _reload(settings, root)
    if maybe_add_gitignore(new_ws):
        return 1
    tx = _start_transaction(new_repo, settings)
    tx.git_reset_head(new_ws.workspace_name, str(root))
    if tx.has_changes():
        _finish(tx, "set git head to working copy parent", settings, new_ws,
                new_repo)
    print("Workspace successfully converted into a colocated Jujutsu/Git "
          "workspace.", file=sys.stderr)
    return 0


def _disable(settings, ws, repo) -> int:
    if not ws.is_colocated():
        print("Workspace is already not colocated with Git.", file=sys.stderr)
        return 0
    root = Path(ws.workspace_root)
    if _is_child_workspace(ws):
        _unlink_worktree(settings, ws, ws.workspace_name)
    else:
        store = Path(ws.repo_path, "store")
        try:
            os.rename(root / ".git", store / "git")
        except OSError as e:
            return _error("Failed to move Git repository to "
                          ".jj/repo/store/git", e)
        _set_bare(store / "git", True)
        (store / "git_target").write_text("git")
    Path(root, ".jj", ".gitignore").unlink(missing_ok=True)
    new_ws, new_repo = _reload(settings, root)
    tx = _start_transaction(new_repo, settings)
    tx.clear_git_head(new_ws.workspace_name)
    if tx.has_changes():
        _finish(tx, "remove git head reference", settings, new_ws, new_repo)
    print("Workspace successfully converted into a non-colocated Jujutsu/Git "
          "workspace.", file=sys.stderr)
    return 0


def _is_child_workspace(ws) -> bool:
    """A secondary workspace: its `.jj/repo` is a file naming the main
    repo, not the repo itself."""
    return Path(ws.workspace_root, ".jj", "repo").is_file()


def _set_bare(git_dir: Path, bare: bool) -> None:
    subprocess.run(["git", "config", "--file", str(git_dir / "config"),
                    "core.bare", "true" if bare else "false"], check=True)


def _reload(settings, root: Path):
    """The workspace again, so it sees the Git repository at its new
    place."""
    ws = pyjj.Workspace.load(settings, str(root))
    return ws, ws.load_at_head()


def _error(message: str, cause: OSError | None = None) -> int:
    print(f"Error: {message}", file=sys.stderr)
    if cause is not None:
        print(f"Caused by: {cause.strerror}", file=sys.stderr)
    return 1
