"""hunk subcommand: hunk_split."""
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

def hunk_split(args) -> int:
    """`pyjj hunk split [-r REV] <spec> <message>` — split with hunk/line spec."""
    try:
        settings, ws, repo = _load(args)
        # Handle spec/message normalization like jj-hunk: spec can be '-' for stdin, --spec, or --spec-file
        spec_str = getattr(args, "spec", None)
        spec_flag = getattr(args, "spec_flag", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        use_stdin = bool(getattr(args, "stdin", False))
        # --spec flag takes precedence over positional spec
        if spec_flag is not None:
            if spec_str is not None or spec_file is not None:
                print("Error: hunk split: use either --spec, --spec-file orpositional <spec>, not both", file=sys.stderr)
                return 2
            spec_str = spec_flag
        # Normalize like jj-hunk's normalize_spec_message
        if spec_file and message is None:
            # When --spec-file is used, the positional spec is actually the message
            message = spec_str
            spec_str = None
        # Resolve message from stdin if requested
        message = _resolve_message_arg(message, use_stdin)
        if message is None:
            print("Error: hunk split requires a commit message (use '-' or --stdin for stdin)", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk split: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk split requires a spec (or use --spec/--spec-file)", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(spec_str, None)
        target = _resolve_one(repo, settings, args.revision or "@")
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        tx = _start_transaction(repo, settings)
        # Use split_selected_edited with overrides
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
