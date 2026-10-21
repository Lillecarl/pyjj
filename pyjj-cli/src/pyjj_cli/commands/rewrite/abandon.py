"""pyjj-cli rewrite command: abandon."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_all,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def abandon(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        revsets = (list(args.revisions_pos or [])
                   + list(getattr(args, "revision_flags", None) or [])) or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to abandon.")
            return 0
        delete_bookmarks = not getattr(args, "retain_bookmarks", False)
        _check_rewritable(tx, settings, targets)
        if getattr(args, "restore_descendants", False):
            # The descendants must keep their trees verbatim, so they are
            # reparented rather than rebased -- one call that abandons and
            # moves together, because the choice lives per commit.
            tx.abandon_restoring_descendants(
                [c.id for c in targets], delete_abandoned_bookmarks=delete_bookmarks)
            _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws,
                    repo, delete_abandoned_bookmarks=delete_bookmarks)
            return 0
        for commit in targets:
            tx.abandon_commit(commit)
        # jj deletes bookmarks pointing at the abandoned commits by
        # default; --retain-bookmarks moves them to the parent instead.
        _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws, repo,
                delete_abandoned_bookmarks=delete_bookmarks)
        return 0
