"""sparse subcommand: sparse_edit."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _run_editor_raw,
    command,
    read_repo,
)
from .update import update_sparse_patterns

if TYPE_CHECKING:
    import argparse


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_edit(args: argparse.Namespace) -> int:
    """`jj sparse edit`: the patterns one per line in the editor, the
    root as `.`."""
    with read_repo(args) as (settings, ws, repo):
        content = "".join(f"{p or '.'}\n" for p in ws.sparse_patterns())
        edited = _run_editor_raw(settings, content, suffix=".jjsparse")
        patterns = []
        for line in edited.splitlines():
            if line.startswith("JJ:"):
                continue
            line = line.strip()
            if not line:
                continue
            try:
                patterns.append(_parse_relative_path(line))
            except ValueError as e:
                print(f"Error: Failed to parse sparse pattern: {line}",
                      file=sys.stderr)
                print(f"Caused by: {e}", file=sys.stderr)
                return 1
        update_sparse_patterns(ws, repo, patterns)
        return 0


def _parse_relative_path(line: str) -> str:
    """`RepoPathBuf::from_relative_path` over a POSIX path: `.` is the
    root, and anything but plain names (`..`, a leading `/` or `./`) is
    refused with jj's own message."""
    if line == ".":
        return ""
    names = []
    for i, part in enumerate(line.split("/")):
        if part == "" and i > 0:
            continue
        if part == "." and i > 0:
            continue
        if part in ("", ".", ".."):
            component = "/" if part == "" else part
            raise ValueError(f'Invalid component "{component}" in '
                             f'repo-relative path "{line}"')
        names.append(part)
    return "/".join(names)
