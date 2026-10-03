"""workspace subcommand: workspace_root."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
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

def workspace_root(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        name = getattr(args, "name", None)
        if not name:
            print(ws.workspace_root)
            return 0
        rel = ws.workspace_path(name)
        if rel is None:
            print(f"Error: No such workspace: {name}", file=sys.stderr)
            return 1
        # The store records the path relative to `.jj/repo`.
        print(os.path.normpath(os.path.join(ws.repo_path, rel)))
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
