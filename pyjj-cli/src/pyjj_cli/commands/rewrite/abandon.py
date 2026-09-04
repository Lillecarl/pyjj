"""pyjj-cli rewrite command: abandon."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _check_rewritable,
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
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def abandon(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revsets = args.revisions_pos or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to abandon.")
            return 0
        delete_bookmarks = not getattr(args, "retain_bookmarks", False)
        tx = repo.start_transaction(settings)
        _check_rewritable(tx, settings, targets)
        if getattr(args, "restore_descendants", False):
            # The descendants must keep their trees verbatim, so they are
            # reparented rather than rebased -- one call that abandons and
            # moves together, because the choice lives per commit.
            tx.abandon_restoring_descendants(
                [c.id for c in targets], delete_bookmarks)
            _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws,
                    repo, delete_abandoned_bookmarks=delete_bookmarks)
            return 0
        for commit in targets:
            tx.abandon_commit(commit)
        # jj deletes bookmarks pointing at the abandoned commits by
        # default; --retain-bookmarks moves them to the parent instead.
        _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws, repo,
                delete_abandoned_bookmarks=delete_bookmarks)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
