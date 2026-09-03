"""operation subcommand: next_commit."""
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

def next_commit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        amount = getattr(args, "amount", 1) or 1
        # Find child of @
        wc = _wc_commit(repo, ws)
        # Find children of wc via revset children(@)
        children = repo.revset(settings, f"children({wc.id.hex()})")
        if not children:
            print("No child revision", file=sys.stderr)
            return 1
        # For amount >1, walk
        target = children[0]
        for _ in range(1, amount):
            nxt = repo.revset(settings, f"children({target.id.hex()})")
            if not nxt:
                break
            target = nxt[0]
        tx = repo.start_transaction(settings)
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"next to {target.id.hex()[:8]}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
