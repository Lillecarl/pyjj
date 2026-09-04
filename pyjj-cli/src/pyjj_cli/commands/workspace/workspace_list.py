"""workspace subcommand: workspace_list."""
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
    _bookmarks_by_commit,
    _commit_context,
    _commit_summary,
    _resolve_template,
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
        settings, ws, repo = _load(args)
        view = repo.view()
        bookmarks = _bookmarks_by_commit(repo)
        template = _resolve_template(settings, ws, args, "workspace_list")
        for name, commit_id in sorted(view.items()):
            commit = repo.get_commit(pyjj.CommitId(commit_id))
            refs = bookmarks.get(commit_id, [])
            if template is not None:
                context = _commit_context(repo, settings, commit, refs)
                context["name"] = name
                print(template.render(context))
                continue
            summary = _commit_summary(repo, settings, commit, refs)
            print(f"{name}: {summary}")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
