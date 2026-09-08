"""tag subcommand: tag_list."""
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
    _ref_list_items,
    _sort_ref_items,
    _formatter,
    _print_ref,
    _resolve_template,
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

def tag_list(args) -> int:
    """`jj tag list` — the bookmark listing, over tags.

    jj builds both from the same `collect_items`, so this reads the
    same helper with the other kind.
    """
    try:
        settings, ws, repo = _load(args)
        template = _resolve_template(settings, ws, args, "tag_list")
        items = _ref_list_items(repo, settings, args, "tag")
        _sort_ref_items(repo, settings, items, args, "tag")
        with _formatter(settings) as fmt:
            for tag, tracked in items:
                _print_ref(repo, settings, tag, template, tracked,
                           kind="tag", fmt=fmt)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
