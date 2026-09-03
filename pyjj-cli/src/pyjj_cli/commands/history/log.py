"""history subcommand: log."""
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

def log(args) -> int:
    try:
        settings, _ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    # Resolve revset if given, else walk from working copies.
    revset_expr = getattr(args, "revisions", None)
    # FILESETS filtering for log is not yet implemented; ignore for now.
    try:
        if revset_expr:
            commits = repo.revset(settings, revset_expr)
            # Topologically sorted by revset engine already; apply limit.
            for commit in commits[: args.limit] if args.limit else commits:
                desc = commit.description.splitlines()[0] if commit.description else "(no description)"
                print(f"@ {commit.id.hex()[:12]} {desc}")
                if getattr(args, "patch", False):
                    # Show patch for each revision vs its first parent (or empty if root)
                    if commit.parent_ids:
                        parent = repo.get_commit(commit.parent_ids[0])
                        for e in parent.diff(commit):
                            print(f"{e.status:8} {e.path}")
                    else:
                        for e in commit.list_files():
                            print(f"added    {e}")
            return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    view = repo.view()
    seen = set()
    queue: list = [(cid, 0) for cid in view.values()]

    while queue and args.limit > 0:
        commit_id_hex, indent = queue.pop(0)
        if commit_id_hex in seen:
            continue
        seen.add(commit_id_hex)

        commit = repo.get_commit(pyjj.CommitId(commit_id_hex))
        prefix = "  " * indent
        desc = commit.description.splitlines()[0] if commit.description else "(no description)"
        print(f"{prefix}@ {commit_id_hex[:12]} {desc}")

        args.limit -= 1
        if indent < 5:
            for parent_id in commit.parent_ids:
                queue.append((parent_id.hex(), indent + 1))

    return 0
