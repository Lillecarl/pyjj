"""workspace subcommand: workspace_add."""
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

def workspace_add(args) -> int:
    """`jj workspace add DESTINATION` — a second working copy on one repo."""
    try:
        settings, ws, repo = _load(args)
        dest = str(Path(args.destination).resolve())
        revs = getattr(args, "revisions", None)
        revision_ids = None
        if revs:
            commits = _resolve_all(repo, settings, revs)
            revision_ids = [c.id for c in commits]
        name = getattr(args, "name", None)
        paragraphs = getattr(args, "messages", None)
        description = join_message_paragraphs(paragraphs) if paragraphs else None
        new_ws, new_repo = ws.add_workspace(
            settings, dest, name=name, revision_ids=revision_ids,
            description=description,
            sparse_patterns=_sparse_patterns(ws, args))
        print(f"Created workspace at {new_ws.workspace_root}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1


def _sparse_patterns(ws, args):
    """What the new workspace's sparse patterns start as.

    A fresh workspace is unrestricted, so `full` -- and the `copy` of an
    unrestricted workspace -- has nothing to set, which is what `None`
    says. `empty` starts with no path at all.
    """
    choice = getattr(args, "sparse_patterns", "copy")
    if choice == "empty":
        return []
    if choice == "full":
        return None
    patterns = ws.sparse_patterns()
    # `[""]` is jj's spelling of "everything", which is where a fresh
    # workspace already starts.
    return None if not patterns or patterns == [""] else patterns
