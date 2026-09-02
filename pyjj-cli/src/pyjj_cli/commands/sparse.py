"""pyjj-cli commands: sparse."""
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

def sparse_list(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        patterns = ws.sparse_patterns()
        for p in patterns:
            print(p if p else ".")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def sparse_set(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        # Get current patterns
        current = ws.sparse_patterns()
        # Handle --clear
        if getattr(args, "clear", False):
            new_patterns: list[str] = []
        else:
            new_patterns = list(current)
        adds = getattr(args, "adds", None) or []
        removes = getattr(args, "removes", None) or []
        for pat in adds:
            if pat not in new_patterns:
                new_patterns.append(pat)
        for pat in removes:
            if pat in new_patterns:
                new_patterns.remove(pat)
        # If after clear and no adds, it means empty sparse (no files) — but jj would keep at least?
        # For reset, we use [""] — for set with --clear and no adds, we set to []
        if not new_patterns and not getattr(args, "clear", False):
            # No change, just list
            for p in current:
                print(p if p else ".")
            return 0
        ws.set_sparse_patterns(new_patterns)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def sparse_reset(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        ws.set_sparse_patterns([""])
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def sparse_edit(args) -> int:
    print("Error: sparse edit is not yet supported (requires an editor)", file=sys.stderr)
    return 2

