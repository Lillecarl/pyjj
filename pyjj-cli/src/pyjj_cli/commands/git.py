"""pyjj-cli commands: git."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from .common import (
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

def git_init(args) -> int:
    """`jj git init` — create a new jj repo backed by an internal Git store."""
    settings = pyjj.UserSettings()
    # Real `jj git init` creates missing parent directories.
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        ws, repo = pyjj.Workspace.init_internal_git(settings, str(destination))
    except pyjj.WorkspaceInitError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Initialized repo in {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0

def git_clone(args) -> int:
    """`jj git clone <source> [destination]` — clone a Git repo."""
    settings = pyjj.UserSettings()
    source = args.source
    # Derive destination from source if not provided, like real jj does
    if args.destination:
        dest = Path(args.destination).resolve()
    else:
        # Take last component of source URL/path, strip .git suffix
        src = source.rstrip("/")
        # Handle URLs like https://github.com/user/repo.git
        # Take after last slash or colon
        if "/" in src:
            base = src.rsplit("/", 1)[-1]
        elif ":" in src:
            base = src.rsplit(":", 1)[-1]
        else:
            base = src
        if base.endswith(".git"):
            base = base[:-4]
        if not base:
            base = "repo"
        dest = Path.cwd() / base
        dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    # Check if dest is empty
    if any(dest.iterdir()):
        print(f"Error: destination path exists and is not an empty directory: {dest}", file=sys.stderr)
        return 1
    colocate = getattr(args, "colocate", True)
    remote_name = getattr(args, "remote_name", "origin") or "origin"
    try:
        ws, repo = pyjj.Workspace.clone_git(settings, source, str(dest), remote_name=remote_name, colocate=colocate)
    except (pyjj.WorkspaceInitError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    print(f"Fetched repo from {source} into {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0

def git_fetch(args) -> int:
    """`jj git fetch` — fetch from a Git remote."""
    try:
        settings, ws, repo = _load(args)
        # Determine remotes
        remotes: list[str] = []
        if getattr(args, "all_remotes", False):
            try:
                remotes = repo.git_remotes()  # type: ignore[attr-defined] - on ReadonlyRepo via Transaction?
            except Exception:
                # Fallback: try via transaction
                tx = repo.start_transaction(settings)
                remotes = tx.git_remotes()
        elif getattr(args, "remote", None):
            remotes = [args.remote]
        else:
            # Default: try to get all remotes, if single, use it, else "origin"
            try:
                all_remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = repo.start_transaction(settings)
                all_remotes = tx.git_remotes()
            if len(all_remotes) == 1:
                remotes = all_remotes
            elif "origin" in all_remotes:
                remotes = ["origin"]
            elif all_remotes:
                remotes = [all_remotes[0]]
            else:
                print("Error: no git remotes configured", file=sys.stderr)
                return 1

        branches = getattr(args, "branches", None) or []
        # For now, handle branches as bookmark names to fetch
        # If no branches specified, fetch all (via git_fetch_all)
        tx = repo.start_transaction(settings)
        for remote in remotes:
            try:
                if branches:
                    # Fetch specific branches
                    result = tx.git_fetch(settings, remote, branches)
                else:
                    result = tx.git_fetch_all(settings, remote)
                # result is a dict with stats, we could print it
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
        _finish(tx, f"fetch from {', '.join(remotes)}", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_push(args) -> int:
    """`jj git push` — push to a Git remote."""
    try:
        settings, ws, repo = _load(args)
        remote = getattr(args, "remote", None)
        if not remote:
            # Try to get default remote from settings or single remote
            try:
                all_remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = repo.start_transaction(settings)
                all_remotes = tx.git_remotes()
            if len(all_remotes) == 1:
                remote = all_remotes[0]
            elif "origin" in all_remotes:
                remote = "origin"
            else:
                print("Error: no remote specified and no default found", file=sys.stderr)
                return 1
        bookmarks = getattr(args, "bookmarks", None) or []
        tags = getattr(args, "tags", None) or []
        all_flag = getattr(args, "all_flag", False)
        # For now, handle bookmarks; if --all, push all bookmarks
        tx = repo.start_transaction(settings)
        if all_flag:
            # Push all bookmarks
            for bm in repo.bookmarks():
                try:
                    tx.git_push_bookmark(settings, remote, bm.name)
                except pyjj.JjError as e:
                    print(f"Warning: failed to push {bm.name}: {getattr(e, 'message', str(e))}", file=sys.stderr)
        elif bookmarks:
            for bm_name in bookmarks:
                try:
                    tx.git_push_bookmark(settings, remote, bm_name)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                    return 1
        elif tags:
            print("Error: pushing tags is not yet supported", file=sys.stderr)
            return 2
        else:
            # Default: push tracked bookmarks (simplified: push all)
            for bm in repo.bookmarks():
                try:
                    tx.git_push_bookmark(settings, remote, bm.name)
                except pyjj.JjError:
                    continue
        _finish(tx, f"push to {remote}", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_import(args) -> int:
    """`jj git import` — update repo with changes from the underlying Git repo."""
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        try:
            tx.git_import_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "import git refs", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_export(args) -> int:
    """`jj git export` — update the underlying Git repo with changes from the repo."""
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        try:
            tx.git_export_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "export git refs", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_remote(args) -> int:
    """`jj git remote` — manage Git remotes."""
    try:
        settings, ws, repo = _load(args)
        cmd = getattr(args, "remote_command", None)
        if cmd == "list":
            try:
                remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = repo.start_transaction(settings)
                remotes = tx.git_remotes()
            for name in sorted(remotes):
                print(name)
            return 0
        elif cmd == "add":
            tx = repo.start_transaction(settings)
            try:
                tx.git_add_remote(args.name, args.url)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"add git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "remove":
            tx = repo.start_transaction(settings)
            try:
                tx.git_remove_remote(args.name)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"remove git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "rename":
            tx = repo.start_transaction(settings)
            try:
                tx.git_rename_remote(args.old, args.new)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"rename git remote {args.old} to {args.new}", settings, ws, repo)
            return 0
        elif cmd == "set-url":
            tx = repo.start_transaction(settings)
            url = getattr(args, "url", None)
            push_url = getattr(args, "push_url", None)
            if url is None and push_url is None:
                print("Error: --url or --push-url is required", file=sys.stderr)
                return 2
            try:
                tx.git_set_remote_urls(args.name, url=url, push_url=push_url)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"set git remote {args.name} URL", settings, ws, repo)
            return 0
        else:
            print("usage: pyjj git remote {add,list,remove,rename,set-url}", file=sys.stderr)
            return 2
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_root(args) -> int:
    """`jj git root` — show the underlying Git directory."""
    try:
        _settings, ws, _repo = _load(args)
        # Try to find .git directory
        ws_root = Path(ws.workspace_root)
        # Check for colocated .git
        git_dir = ws_root / ".git"
        if git_dir.exists():
            print(str(git_dir.resolve()))
            return 0
        # Otherwise, it's stored in .jj/repo/store/git
        repo_path = Path(ws.repo_path)
        git_store = repo_path / "store" / "git"
        if git_store.exists():
            print(str(git_store.resolve()))
            return 0
        # Fallback to repo_path
        print(str(repo_path))
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def git_colocation(args) -> int:
    """`jj git colocation` — manage colocation status."""
    try:
        _settings, ws, _repo = _load(args)
        sub = getattr(args, "colocation_command", None)
        ws_root = Path(ws.workspace_root)
        git_dir = ws_root / ".git"
        is_colocated = git_dir.exists()
        if sub == "status":
            if is_colocated:
                print("Colocated with Git")
            else:
                print("Not colocated with Git")
            return 0
        elif sub == "enable":
            if is_colocated:
                print("Already colocated", file=sys.stderr)
                return 0
            # Enabling colocation would require moving the git dir from .jj/repo/store/git to .git
            # This is not yet implemented in pyjj — we just report and return error
            print("Error: converting to colocated repo is not yet supported", file=sys.stderr)
            return 1
        elif sub == "disable":
            if not is_colocated:
                print("Already not colocated", file=sys.stderr)
                return 0
            print("Error: converting to non-colocated repo is not yet supported", file=sys.stderr)
            return 1
        else:
            print("usage: pyjj git colocation {status,enable,disable}", file=sys.stderr)
            return 2
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

