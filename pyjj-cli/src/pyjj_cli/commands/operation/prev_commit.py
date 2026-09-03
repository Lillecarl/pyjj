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
    _move_to,
    _walk,
    _wants_edit,
)

def prev_commit(args) -> int:
    """`jj prev [OFFSET]`: move the working copy backward.

    Without `--edit` the new working copy is a *child* of the ancestor
    `offset` steps behind `@`'s parent -- one more step back than
    `--edit` takes, because the new commit then sits where `@` used to
    relative to that ancestor. With `--edit` the working copy becomes the
    ancestor `offset` steps behind `@`.
    """
    try:
        settings, ws, repo = _load(args)
        offset = getattr(args, "amount", 1) or 1
        edit = _wants_edit(args)
        wc = _wc_commit(repo, ws)

        steps = offset if edit else offset + 1
        targets = _walk(repo, settings, [wc.id.hex()], "parents", steps)
        if not targets:
            print(f"Error: No ancestor found {offset} commit(s) back from the "
                  "working copy", file=sys.stderr)
            return 1

        return _move_to(args, settings, ws, repo, targets, edit, "prev")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
