"""operation subcommand: evolog."""
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

def evolog(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        rev = getattr(args, "revisions", "@")
        commits = repo.revset(settings, rev)
        if not commits:
            print("No revisions to show")
            return 0
        # For now, just show the log for the revision's change id's evolution
        # Use the commit's change id to find all commits with same change id via revset?
        # Simplified: just show the single commit
        for c in commits:
            desc = c.description.splitlines()[0] if c.description else "(no description)"
            print(f"{c.change_id.hex()[:12]} {c.id.hex()[:12]} {desc}")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
