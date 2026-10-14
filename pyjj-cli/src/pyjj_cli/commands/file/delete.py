"""file subcommand: delete."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_one,
)

def file_delete(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [commit])
        matched, _unmatched = commit.match_filesets(
            settings, ws.workspace_root, list(getattr(args, "filesets", [])))
        # No warning for unmatched patterns: real `jj file delete`
        # silently deletes what matches and reports `Nothing changed.`
        # (on stderr) when nothing did.
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
                restore_descendants=getattr(args, "restore_descendants", False))
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
