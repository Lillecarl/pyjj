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
    try:
        _settings, _ws, repo = _load(args)
        names = getattr(args, "names", None) or []
        tags = repo.tags()  # list[Tag]
        if names:
            tags = [t for t in tags if t.name in names]
        for tag in sorted(tags, key=lambda t: t.name):
            if tag.has_conflict:
                ids = " ".join(t.hex()[:12] for t in tag.target_ids)
                print(f"{tag.name}@conflicted: {ids}")
            elif tag.target_ids:
                print(f"{tag.name}: {tag.target_ids[0].hex()[:12]}")
            else:
                print(f"{tag.name}: (deleted)")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
