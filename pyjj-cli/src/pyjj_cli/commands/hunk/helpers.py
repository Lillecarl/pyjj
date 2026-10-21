"""hunk subcommand: _load_spec."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj.hunk as hunk_mod

if TYPE_CHECKING:
    import argparse

def _load_spec(args: argparse.Namespace) -> hunk_mod.Spec:
    """Load spec from args.spec / args.spec_file / stdin, handling '-'."""
    spec_str = getattr(args, "spec", None)
    spec_file = getattr(args, "spec_file", None)
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

def _hunk_spec(args: argparse.Namespace, cmd: str, *, require_message: bool) -> tuple[hunk_mod.Spec, str | None] | None:
    """Normalize `--spec`/`--spec-file`/positional `<spec>` (+ message) into a loaded Spec.

    `cmd` is the command name used in refusal text (e.g. `"hunk split"`).
    Prints the refusal and returns `None` on bad argv; the caller returns 2.
    With `require_message`, also resolves the commit message from `-`/`--stdin`
    and refuses when it is missing. Only arg normalization lives here --
    selection semantics stay in each command.
    """
    spec_str = getattr(args, "spec", None)
    spec_flag = getattr(args, "spec_flag", None)
    spec_file = getattr(args, "spec_file", None)
    message = getattr(args, "message", None)
    if spec_flag is not None:
        if require_message and message is None:
            message, spec_str = spec_str, None
        if spec_str is not None or spec_file is not None:
            print(f"Error: {cmd}: use either --spec, --spec-file or positional <spec>, not both", file=sys.stderr)
            return None
        spec_str = spec_flag
    if require_message and spec_file and message is None:
        # When --spec-file is used, the positional spec is actually the message.
        message = spec_str
        spec_str = None
    if require_message:
        message = _resolve_message_arg(message, bool(getattr(args, "stdin", False)))
        if message is None:
            print(f"Error: {cmd} requires a commit message (use '-' or --stdin for stdin)", file=sys.stderr)
            return None
    if spec_file:
        if spec_str is not None:
            print(f"Error: {cmd}: omit <spec> when using --spec-file", file=sys.stderr)
            return None
        return hunk_mod.load_spec_from_input(None, spec_file), message
    if spec_str is None:
        print(f"Error: {cmd} requires a spec (or use --spec/--spec-file)", file=sys.stderr)
        return None
    return hunk_mod.load_spec_from_input(spec_str, None), message
