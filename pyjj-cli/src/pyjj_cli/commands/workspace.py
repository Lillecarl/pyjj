"""pyjj-cli commands: workspace."""
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

def workspace_list(args) -> int:
    try:
        _settings, ws, repo = _load(args)
        view = repo.view()
        for name, commit_id in sorted(view.items()):
            # Try to get workspace path
            try:
                ws_path = ws.workspace_path(name)
                path_str = ws_path if ws_path else "(unknown)"
            except Exception:
                path_str = "(unknown)"
            print(f"{name}: {commit_id[:12]} {path_str}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def workspace_add(args) -> int:
    try:
        settings, ws, repo = _load(args)
        dest = str(Path(args.destination).resolve())
        revs = getattr(args, "revisions", None)
        revision_ids = None
        if revs:
            commits = _resolve_all(repo, settings, revs)
            revision_ids = [c.id for c in commits]
        name = getattr(args, "name", None)
        new_ws, new_repo = ws.add_workspace(settings, dest, name=name, revision_ids=revision_ids)
        print(f"Created workspace at {new_ws.workspace_root}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def workspace_forget(args) -> int:
    try:
        settings, ws, _repo = _load(args)
        names = getattr(args, "names", [])
        ws.forget_workspaces(settings, names)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def workspace_rename(args) -> int:
    try:
        settings, ws, _repo = _load(args)
        new_name = getattr(args, "new_name", "")
        ws.rename_workspace(settings, new_name)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def workspace_root(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        print(ws.workspace_root)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def workspace_update_stale(args) -> int:
    try:
        settings, ws, repo = _load(args)
        # repo is already at head via _load, so we can check if ws is stale
        result = ws.update_stale(repo)
        if result is None:
            print("Working copy is not stale")
        else:
            print(f"Updated stale working copy: {result}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

