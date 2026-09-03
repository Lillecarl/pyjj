"""tag subcommand: tag_set."""
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

def tag_set(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        target = _resolve_one(repo, settings, rev)
        # jj refuses to move a tag that already exists unless asked --
        # a tag is meant to stay put, unlike a bookmark.
        names = list(getattr(args, "names", []))
        if not getattr(args, "allow_move", False):
            for name in names:
                if repo.get_tag(name) is not None:
                    print(f"Error: Refusing to move tag: {name}", file=sys.stderr)
                    print("Hint: Use --allow-move to update existing tags.",
                          file=sys.stderr)
                    return 1
        tx = repo.start_transaction(settings)
        for name in names:
            tx.set_tag(name, target.id)
        _finish(tx, f"set tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
