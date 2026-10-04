"""git subcommand: git_init."""
import subprocess
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
    _start_transaction,
    apply_config_args,
)

def git_init(args) -> int:
    """`jj git init` — create a new jj repo backed by Git.

    jj puts the git repo at the workspace root by default, so git tools
    see it too. `git.colocate = false` turns that off, and
    `--no-colocate` turns it off for one repo; `--colocate` only matters
    when the config already turned it off.
    """
    settings = apply_config_args(pyjj.UserSettings())
    if getattr(args, "colocate", False) and getattr(args, "no_colocate", False):
        print("Error: --colocate cannot be used with --no-colocate",
              file=sys.stderr)
        return 2
    git_repo = getattr(args, "git_repo", None)
    if git_repo and getattr(args, "colocate", False):
        print("Error: --colocate cannot be used with --git-repo",
              file=sys.stderr)
        return 2
    colocate = settings.get_bool("git.colocate")
    if colocate is None:
        colocate = True
    if getattr(args, "colocate", False):
        colocate = True
    if getattr(args, "no_colocate", False):
        colocate = False
    # Real `jj git init` creates missing parent directories.
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if git_repo:
            # A path naming the git dir itself wins; otherwise a `.git`
            # inside it does (a working copy); otherwise it is a bare
            # repo as given. Same probing real jj does.
            candidate = (Path.cwd() / git_repo).resolve()
            if candidate.suffix != ".git" and (candidate / ".git").is_dir():
                candidate = candidate / ".git"
            ws, repo = pyjj.Workspace.init_external_git(
                settings, str(destination), str(candidate))
            # Import its branches and tags, the way real init does.
            tx = _start_transaction(repo, settings)
            tx.git_import_refs()
            tx.rebase_descendants()
            repo = tx.commit("import git refs")
            repo = _check_out_git_head(
                settings, ws.workspace_name, destination, candidate, repo)
        else:
            init = (pyjj.Workspace.init_colocated_git if colocate
                    else pyjj.Workspace.init_internal_git)
            ws, repo = init(settings, str(destination),
                            getattr(args, "object_hash", None))
    except pyjj.WorkspaceInitError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Initialized repo in {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0


def _check_out_git_head(settings, workspace_name: str, destination: Path,
                          git_dir: Path, repo):
    """Move a fresh external init onto a child of the git HEAD commit,
    returning the repo to print.

    Real init checks the git HEAD out, so `@` is an empty commit on top
    of whatever the backing repo had checked out, with its files on
    disk -- not the blank root child `init_external_git` leaves. The
    HEAD symref is read with git itself (a bare `rev-parse` fallback
    is skipped: resolving a raw sha to its imported commit has no
    binding, and an unborn or detached HEAD simply keeps the fresh
    working copy, as real init does too).
    """
    head = subprocess.run(
        ["git", f"--git-dir={git_dir}", "symbolic-ref", "-q", "HEAD"],
        capture_output=True, text=True,
    )
    if head.returncode != 0:
        return repo
    ref = head.stdout.strip()
    if not ref.startswith("refs/heads/"):
        return repo
    bookmark = repo.get_bookmark(ref[len("refs/heads/"):])
    if bookmark is None or bookmark.has_conflict or not bookmark.target_ids:
        return repo
    tx = _start_transaction(repo, settings)
    builder = tx.new_commit(settings, [bookmark.target_ids[0]])
    child = builder.write(repo)
    tx.edit(workspace_name, child)
    tx.rebase_descendants()
    repo = tx.commit("import git head")
    fresh = pyjj.Workspace.load(settings, str(destination))
    fresh_repo = fresh.load_at_head()
    fresh.check_out(fresh_repo, fresh_repo.get_commit(child.id))
    return fresh.load_at_head()
