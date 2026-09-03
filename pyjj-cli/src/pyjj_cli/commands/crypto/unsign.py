"""crypto subcommand: unsign."""
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

def unsign(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revs = getattr(args, "revisions", None) or ["@"]
        targets = _resolve_all(repo, settings, revs)
        tx = repo.start_transaction(settings)
        for commit in targets:
            b = tx.rewrite_commit(settings, commit)
            b.set_sign_behavior("drop")
            b.write(repo)
        _finish(tx, f"unsign {len(targets)} commits", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
