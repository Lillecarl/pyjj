"""bookmark subcommand: bookmark_advance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _finish,
    _resolve_one,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def bookmark_advance(args: argparse.Namespace) -> int:
    """`jj bookmark advance [NAMES] --to <rev>`: move bookmarks forward.

    Only a named bookmark that already sits on an ancestor of the target
    moves, and only if it is not there already -- advancing is a
    fast-forward, never a jump sideways. Without names jj advances the
    bookmarks that `advance-bookmarks` opts in, which pyjj does not read,
    so no names means nothing moves.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        names = list(getattr(args, "names", []) or [])
        target = _resolve_one(repo, settings, getattr(args, "to", "@") or "@")
        target_hex = target.id.hex()

        eligible = {
            c.id.hex()
            for c in repo.revset(settings, f"::{target_hex}")
        }
        moved = []
        for bookmark in repo.bookmarks():
            if bookmark.name not in names:
                continue
            here = [i.hex() for i in bookmark.target_ids]
            if here == [target_hex] or not all(h in eligible for h in here):
                continue
            moved.append(bookmark.name)

        if not moved:
            print("No bookmarks to update.")
            return 0

        for name in moved:
            tx.set_bookmark(name, target.id)
        _finish(tx, f"advance bookmarks to {target_hex[:8]}", settings, ws, repo)
        print(f"Advanced {len(moved)} bookmarks to {target_hex[:8]}")
        return 0
