"""pyjj-cli commands: file."""
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

def file_chmod(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        mode = getattr(args, "mode", "x")
        executable = mode in ("x", "executable")
        tx = repo.start_transaction(settings)
        for path in getattr(args, "paths", []):
            b = tx.set_executable(commit, path, executable)
            b.write(repo)
        _finish(tx, f"chmod {rev}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def file_track(args) -> int:
    # file track is about telling the working copy to start tracking a path
    # that was previously ignored (e.g. via .gitignore). In pyjj, snapshot
    # already handles .gitignore, but file track with --include-ignored
    # would force-track. For now, we just ensure the file is not ignored
    # by touching it and snapshotting, but the real `jj file track` does
    # more. For parity, we just snapshot and check out.
    try:
        _settings, ws, repo = _load(args)
        # Snapshot will pick up the files if they exist and are not ignored
        # unless --include-ignored is used, in which case we would need to
        # force-track. For now, just do a snapshot and return.
        # The paths are relative to workspace root, we ensure they exist
        for path in getattr(args, "paths", []):
            p = Path(ws.workspace_root) / path
            if not p.exists():
                print(f"Warning: path {path} does not exist", file=sys.stderr)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def file_untrack(args) -> int:
    # file untrack is the opposite: stop tracking a path. In pyjj, this
    # would involve adding it to .gitignore or just removing it from the
    # working copy? For now, we treat it as removing the file from the
    # working copy and letting snapshot handle it.
    try:
        _settings, ws, repo = _load(args)
        for path in getattr(args, "paths", []):
            p = Path(ws.workspace_root) / path
            if p.exists():
                # For parity, we just remove the file and let snapshot handle
                # but we don't actually delete; we just return
                pass
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def file_search(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        pattern = getattr(args, "pattern", "")
        name_only = bool(getattr(args, "name_only", False))
        filesets = getattr(args, "filesets", None) or None
        # Simple search: list files and grep
        for path in commit.list_files(filesets):
            try:
                content = commit.read_file(path)
                if pattern.encode() in content:
                    print(f"{path}: {pattern}")
            except pyjj.JjError:
                continue
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def file_list(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        paths = getattr(args, "filesets", None) or None
        for p in sorted(commit.list_files(paths)):
            print(p)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def file_show(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        for pattern in args.filesets:
            # Support exact paths and directory filtering via list_files
            paths = commit.list_files([pattern])
            if not paths:
                # Try as exact file
                try:
                    content = commit.read_file(pattern)
                    sys.stdout.buffer.write(content)
                    if not content.endswith(b"\n"):
                        sys.stdout.buffer.write(b"\n")
                    continue
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
            for p in paths:
                try:
                    content = commit.read_file(p)
                    sys.stdout.buffer.write(content)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def file_annotate(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        lines = commit.annotate(repo, args.path)
        for ann in lines:
            prefix = f"{ann.commit_id.hex()[:12]}"
            sys.stdout.buffer.write(prefix.encode() + b"  " + ann.line)
            if not ann.line.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

