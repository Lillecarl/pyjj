"""operation subcommand: prev_commit."""
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

def prev_commit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        amount = getattr(args, "amount", 1) or 1
        wc = _wc_commit(repo, ws)
        if not wc.parent_ids:
            print("No parent revision", file=sys.stderr)
            return 1
        target = repo.get_commit(wc.parent_ids[0])
        for _ in range(1, amount):
            if not target.parent_ids:
                break
            target = repo.get_commit(target.parent_ids[0])
        tx = repo.start_transaction(settings)
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"prev to {target.id.hex()[:8]}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
