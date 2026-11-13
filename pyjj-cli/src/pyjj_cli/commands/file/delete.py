"""file subcommand: delete."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_one,
    _ui_path_formatter,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def file_delete(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        _check_rewritable(tx, settings, [commit])
        matched, unmatched = commit.match_filesets(
            settings, ws.workspace_root, list(getattr(args, "filesets", [])),
            cwd=os.getcwd())
        if unmatched:
            ui_path = _ui_path_formatter(ws)
            print("Warning: No matching entries for paths: "
                  + ", ".join(ui_path(path) for path in unmatched), file=sys.stderr)
        if not matched:
            print("Nothing changed.", file=sys.stderr)
            return 0
        builder = tx.edit_commit_tree(
            commit, {path: None for path in matched})
        rewritten = builder.write(repo)
        if commit.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, rewritten.id)
        _finish(tx, f"delete paths in commit {commit.id.hex()}",
                settings, ws, repo,
                restore_descendants=getattr(args, "restore_descendants", False), trial=args)
        return 0
