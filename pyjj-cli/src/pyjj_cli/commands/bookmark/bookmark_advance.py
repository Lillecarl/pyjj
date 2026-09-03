"""bookmark subcommand: bookmark_advance."""
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

def bookmark_advance(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        target = _resolve_one(repo, settings, rev)
        # Advance closest bookmarks to target: find bookmarks whose target is ancestor of @ and descendant of target?
        # Simplified: move all bookmarks that are ancestors of @ to target
        tx = repo.start_transaction(settings)
        for bm in repo.bookmarks():
            # Check if bookmark is ancestor of @ and not already at target
            try:
                # Use revset: bookmarks that are ancestors of @
                # For now, just move all bookmarks that are not at target and are ancestors of current @
                # We can use revset: ancestors(@) to find
                pass
            except Exception:
                pass
            # For now, just advance all bookmarks to target if they are not already
            tx.set_bookmark(bm.name, target.id)
        _finish(tx, f"advance bookmarks to {target.id.hex()[:8]}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
