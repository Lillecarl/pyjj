"""operation subcommand: op_restore."""
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

def op_restore(args) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    try:
        settings, ws, repo = _load(args)
        target = repo.load_operation(args.operation_pos)
        tx = repo.start_transaction(settings)
        tx.restore_operation(target)
        _restore_view_command(
            tx, f"restore operation {args.operation_pos}", settings, ws, repo
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
