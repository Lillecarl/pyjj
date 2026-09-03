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
    """`jj bookmark advance [NAMES] --to <rev>`: move bookmarks forward.

    Only a named bookmark that already sits on an ancestor of the target
    moves, and only if it is not there already -- advancing is a
    fast-forward, never a jump sideways. Without names jj advances the
    bookmarks that `advance-bookmarks` opts in, which pyjj does not read,
    so no names means nothing moves.
    """
    try:
        settings, ws, repo = _load(args)
        names = list(getattr(args, "names", []) or [])
        target = _resolve_one(repo, settings, getattr(args, "to", "@") or "@")
        target_hex = target.id.hex()

        eligible = {
            c.id.hex()
            for c in repo.revset(settings, f"::{target_hex}")
        }
        moved = []
        for bookmark in repo.bookmarks():
            if bookmark.name not in names:
                continue
            here = [i.hex() for i in bookmark.target_ids]
            if here == [target_hex] or not all(h in eligible for h in here):
                continue
            moved.append(bookmark.name)

        if not moved:
            print("No bookmarks to update.")
            return 0

        tx = repo.start_transaction(settings)
        for name in moved:
            tx.set_bookmark(name, target.id)
        _finish(tx, f"advance bookmarks to {target_hex[:8]}", settings, ws, repo)
        print(f"Advanced {len(moved)} bookmarks to {target_hex[:8]}")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
