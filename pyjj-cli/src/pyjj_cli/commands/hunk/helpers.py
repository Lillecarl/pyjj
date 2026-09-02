"""hunk subcommand: _load_spec."""
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
    _wc_commit,
    complete_newline,
    _run_editor,
)

def _load_spec(args) -> hunk_mod.Spec:
    """Load spec from args.spec / args.spec_file / stdin, handling '-'."""
    spec_str = getattr(args, "spec", None)
    spec_file = getattr(args, "spec_file", None)
    # Handle case where spec_file is provided and spec is None, but message is in spec position
    # For hunk split, args has spec and message; for commit, similar.
    # The _load_spec_from_input helper already handles '-'
    return hunk_mod.load_spec_from_input(spec_str, spec_file)

def _resolve_message_arg(msg: str | None, use_stdin: bool) -> str | None:
    """Resolve commit message: '-' or --stdin reads from stdin (supports long messages without quoting)."""
    if use_stdin:
        text = sys.stdin.read()
        if not text.strip():
            return None
        return text
    if msg == "-":
        text = sys.stdin.read()
        if not text:
            return None
        return text
    return msg
