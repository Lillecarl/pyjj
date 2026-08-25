"""CLI command implementations exercising pyjj bindings."""

import sys
from pathlib import Path

import pyjj


def init(args) -> int:
    """Initialize a new jj repository."""
    path = args.path or "."
    settings = pyjj.UserSettings()

    ws, repo = pyjj.Workspace.init_internal_git(settings, str(Path(path).resolve()))

    view = repo.view()
    print(f"Initialized jj repo in {ws.workspace_root}")
    print(f"  Repo path:     {ws.repo_path}")
    for ws_name, commit_id in view.items():
        print(f"  Working copy [{ws_name}]: {commit_id[:12]}")
    return 0


def _resolve_workspace(args) -> tuple:
    """Resolve workspace path and load workspace + repo."""
    settings = pyjj.UserSettings()
    cwd = args.path or str(Path.cwd())
    ws_path = str(Path(cwd).resolve())

    ws = pyjj.Workspace.load(settings, ws_path)
    repo = ws.load_at_head()
    return ws, repo, settings


def status(args) -> int:
    """Show working copy status."""
    try:
        ws, repo, _settings = _resolve_workspace(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Workspace: {ws.workspace_root}")
    print(f"  Repo path: {ws.repo_path}")

    view = repo.view()
    for ws_name, commit_id in view.items():
        print(f"  Working copy [{ws_name}]: {commit_id[:12]}")

    return 0


def log(args) -> int:
    """Show commit history."""
    try:
        _ws, repo, _settings = _resolve_workspace(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    limit = args.limit or 10
    view = repo.view()
    seen = set()
    queue: list = [(cid, 0) for cid in view.values()]

    while queue and limit > 0:
        commit_id_hex, indent = queue.pop(0)
        if commit_id_hex in seen:
            continue
        seen.add(commit_id_hex)

        commit = repo.get_commit(pyjj.CommitId(commit_id_hex))
        prefix = "  " * indent
        desc = commit.description.splitlines()[0] if commit.description else "(no description)"
        print(f"{prefix}@ {commit_id_hex[:12]} {desc}")
        print(f"{prefix}  author: {commit.author.name} <{commit.author.email}>")

        limit -= 1
        if indent < 5:
            for parent_id in commit.parent_ids:
                queue.append((parent_id.hex(), indent + 1))

    return 0


def complete_newline(s: str) -> str:
    """Append one trailing newline to a non-empty description lacking one.

    Mirrors the real jj CLI's text_util::complete_newline, which wraps
    every description-producing path (-m/--stdin/editor). jj_lib stores
    descriptions verbatim; this normalization is a CLI convention.
    """
    if s and not s.endswith("\n"):
        return s + "\n"
    return s


def describe(args) -> int:
    """Set working-copy commit description (snapshot + describe)."""
    try:
        _ws, repo, settings = _resolve_workspace(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    description = complete_newline(" ".join(args.message))
    if not description.strip():
        print("Error: description required", file=sys.stderr)
        return 1

    tx = repo.start_transaction(settings)

    view = repo.view()
    wc_commit_ids = list(view.values())
    if not wc_commit_ids:
        print("Error: no working copy commit", file=sys.stderr)
        return 1

    wc_commit_id = wc_commit_ids[0]
    wc_commit = repo.get_commit(pyjj.CommitId(wc_commit_id))

    builder = tx.rewrite_commit(settings, wc_commit)
    builder.set_description(description)
    snapshot = builder.write(repo)

    wid = snapshot.id
    print(f"  Rewrote commit: {wid.short(12)} -> {wid.hex()}")

    # Update working copy refs
    for ws_name, _old_id in view.items():
        tx.set_wc_commit(ws_name, snapshot.id)

    num_rebased = tx.rebase_descendants()
    wc_name = list(view.keys())[0] if view else "default"
    new_repo = tx.commit(f"describe: {description}")

    print(f"  Rebased: {num_rebased} descendants")
    print(f"  Committed: {new_repo}")

    return 0


def version(args) -> int:
    """Show version information."""
    print(f"pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
