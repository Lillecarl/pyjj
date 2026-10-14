"""file subcommand: delete."""
import sys

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_one,
    command,
    write_tx,
)

@command
def file_delete(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
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
