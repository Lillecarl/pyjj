"""describe subcommand: describe."""
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
    _check_rewritable,
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

def describe(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    revsets = list(args.revisions_pos or [])
    if args.revisions_opt:
        revsets.extend(args.revisions_opt)

    if args.stdin:
        description = sys.stdin.read()
    elif args.messages:
        description = join_message_paragraphs(args.messages)
    elif len(revsets) <= 1:
        # Bare `describe` (or a single revision): the editor path.
        base_commit = _resolve_one(repo, settings, revsets[0] if revsets else "@")
        description = _run_editor(settings, base_commit.description)
    else:
        print("Error: bulk description editing is not supported; pass -m "
              "or --stdin", file=sys.stderr)
        return 2

    if not revsets:
        revsets = ["@"]

    try:
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to describe.")
            return 0

        tx = repo.start_transaction(settings)
        _check_rewritable(tx, settings, targets)
        new_wc_id = None
        wc_id = repo.view().get(ws.workspace_name)
        for commit in targets:
            builder = (
                tx.rewrite_commit(settings, commit)
                .set_description(description)
            )
            new_commit = builder.write(repo)
            if commit.id.hex() == wc_id:
                new_wc_id = new_commit.id
        if new_wc_id is not None:
            tx.set_wc_commit(ws.workspace_name, new_wc_id)
        _finish(tx, f"describe commit {targets[0].id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
