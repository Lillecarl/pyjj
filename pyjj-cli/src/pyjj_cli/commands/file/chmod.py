"""file subcommand: file_chmod."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _check_rewritable,
    _cli_paths,
    _finish,
    _resolve_one,
    _warn_unmatched_paths,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def file_chmod(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        mode = getattr(args, "mode", "x")
        executable = mode in ("x", "executable")
        _check_rewritable(tx, settings, [commit])
        paths = _cli_paths(ws, getattr(args, "paths", []))
        _warn_unmatched_paths(ws, paths, [commit])
        for path in paths:
            if commit.file_kind(path) == "absent":
                continue
            b = tx.set_executable(commit, path, executable)
            b.write(repo)
        _finish(tx, f"chmod {rev}", settings, ws, repo, trial=args)
        return 0
