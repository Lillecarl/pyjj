"""bookmark subcommand: bookmark_untrack."""
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
    _start_transaction,
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
    _split_remote_ref,
)

def bookmark_untrack(args) -> int:
    try:
        settings, ws, repo = _load(args)
        default_remote = getattr(args, "remote", None)
        tx = _start_transaction(repo, settings)
        for name in getattr(args, "names", []):
            bookmark, remote = _split_remote_ref(name, default_remote)
            tx.git_untrack_remote_bookmark(remote, bookmark)
        _finish(tx, f"untrack remote bookmark {', '.join(getattr(args, 'names', []))}",
                settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
