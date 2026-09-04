"""hunk subcommand: hunk_commit."""
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
    _wc_commit,
    complete_newline,
    _run_editor,
)
from .helpers import _resolve_message_arg

def hunk_commit(args) -> int:
    """`pyjj hunk commit <spec> <message>` — commit selected hunks from working copy."""
    try:
        settings, ws, repo = _load(args)
        spec_str = getattr(args, "spec", None)
        spec_flag = getattr(args, "spec_flag", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        use_stdin = bool(getattr(args, "stdin", False))
        if spec_flag is not None:
            if spec_str is not None or spec_file is not None:
                print("Error: hunk commit: use either --spec, --spec-file or positional <spec>, not both", file=sys.stderr)
                return 2
            spec_str = spec_flag
        if spec_file and message is None:
            message = spec_str
            spec_str = None
        message = _resolve_message_arg(message, use_stdin)
        if message is None:
            print("Error: hunk commit requires a commit message (use '-' or --stdin for stdin)", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk commit: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk commit requires a spec (or use --spec/--spec-file)", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(spec_str, None)
        # For commit, the target is the working copy commit
        target = _wc_commit(repo, ws)
        # Collect file contents for working copy changes? For commit, we need to snapshot working copy
        # The working copy's changes are not yet in a commit; we need to use the working copy's file contents
        # For now, we treat the working copy's parent as the base, similar to split
        # Use the same spec_to_overrides but for the working copy's diff against parent
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        tx = _start_transaction(repo, settings)
        # For commit, we want to keep selected changes in the current commit, and leave the rest in a new child
        # This is the same as split, but the current commit is the working copy
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
