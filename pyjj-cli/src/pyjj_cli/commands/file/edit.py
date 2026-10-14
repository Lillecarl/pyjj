"""file subcommand: edit."""
import os
import subprocess
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_one,
    _run_editor_raw,
)

def file_edit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        # jj resolves the path against the workspace and normalizes it;
        # the op description carries the normalized spelling.
        path = os.path.normpath(args.path)
        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [commit])
        kind = commit.file_kind(path)
        if kind == "dir":
            print(f"Error: Path is a directory: {path}", file=sys.stderr)
            return 1
        if kind in ("symlink", "submodule"):
            print(f"Error: Path '{path}' is not a regular file",
                  file=sys.stderr)
            return 1
        if kind == "other-conflict":
            print(f"Error: Path '{path}' has a non-file conflict and "
                  f"cannot be edited", file=sys.stderr)
            return 1
        if kind == "file-conflict":
            old = bytes(commit.materialize_conflict(settings, path))
        elif kind == "file":
            old = bytes(commit.read_file(path))
        else:  # absent: the editor starts empty, saving creates the file
            old = b""
        try:
            # Raw bytes through a text editor: decode for the round
            # trip, `surrogateescape` so undecodable bytes survive it.
            # No cleanup -- jj snapshots whatever the editor saved,
            # blank edges and all.
            new = _run_editor_raw(
                settings, old.decode("utf-8", "surrogateescape")).encode(
                    "utf-8", "surrogateescape")
        except subprocess.CalledProcessError as e:
            print(f"Error: editor exited with status {e.returncode}",
                  file=sys.stderr)
            return 1
        if new == old and kind != "absent":
            # Untouched -- including untouched conflict markers, which
            # `resolve_conflict` would otherwise rewrite verbatim. An
            # absent path is exempt: saving the empty seed creates the
            # file, and jj records that as a change.
            print("Nothing changed.", file=sys.stderr)
            return 0
        if kind == "file-conflict":
            builder = tx.resolve_conflict(commit, path, new)
        else:
            builder = tx.edit_commit_tree(commit, {path: new})
        rewritten = builder.write(repo)
        if commit.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, rewritten.id)
        _finish(tx, f"edit file {path} in commit {commit.id.hex()}",
                settings, ws, repo,
                restore_descendants=getattr(args, "restore_descendants", False))
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
