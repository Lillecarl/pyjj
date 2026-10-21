"""command: parallelize — make a chain of revisions siblings."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    _check_rewritable,
    _finish,
    _reload,
    _resolve_all,
    _start_transaction,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Sequence

    import pyjj


@command
def parallelize(args: argparse.Namespace) -> int:
    """`jj parallelize [REVSETS]`: turn a chain into siblings.

    Every target ends up on the parents the chain itself hung from, and
    whatever followed the chain ends up on all of them at once. Content
    is preserved: a target that used to sit on another loses that one's
    changes when it moves off it.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        revisions = (list(getattr(args, "revisions", None) or [])
                     + list(getattr(args, "revisions_pos", None) or []))
        targets = _resolve_all(repo, settings, revisions or ["@"])
        if len(targets) < 2:
            print("Nothing changed.", file=sys.stderr)
            return 0

        union = "|".join(c.id.hex() for c in targets)
        # The chain hangs from these; every target moves onto them.
        outside_parents = repo.revset(settings, f"parents({union}) ~ ({union})")
        outside_ids = [c.id for c in outside_parents]
        outside_hexes = {c.id.hex() for c in outside_parents}
        followers = repo.revset(settings, f"children({union}) ~ ({union})")
        # Change ids survive a rewrite; commit ids do not, and the
        # followers have to be reconnected after every target has moved.
        # Root-first, because a merge's parent order is part of its
        # commit id and jj keeps the order the chain had.
        target_changes = [c.change_id.reverse_hex() for c in reversed(targets)]
        follower_changes = [c.change_id.reverse_hex() for c in followers]

        # jj checks only the commits whose parent list changes, which is
        # narrower than the target set: the chain's own root already hangs
        # from the outside parents, so parallelizing never rewrites it.
        needs_rewrite = [c for c in targets
                         if {p.hex() for p in c.parent_ids} != outside_hexes]

        if not needs_rewrite:
            print("Nothing changed.", file=sys.stderr)
            return 0

        _check_rewritable(tx, settings, needs_rewrite)
        for commit in needs_rewrite:
            # One target at a time: `move_commits` keeps the edges
            # *among* its targets, which is exactly what parallelizing
            # has to break.
            tx.move_commits(target_commit_ids=[commit.id], target_root_ids=[],
                            new_parent_ids=outside_ids, new_child_ids=[])
        _finish(tx, f"parallelize {len(targets)} commits", settings, ws, repo)

        if follower_changes:
            _reconnect(args, settings, target_changes, follower_changes)
        return 0


def _reconnect(args: argparse.Namespace, settings: pyjj.UserSettings,
               target_changes: Sequence[str], follower_changes: Sequence[str]):
    """Put every follower on all of the now-parallel targets."""
    ws, repo = _reload(settings, args)
    # Not write_tx: the repo here comes from _reload, and a fresh _load
    # would rebuild settings and reseed the change-id RNG.
    targets = _by_change_id(repo, settings, target_changes)
    followers = _by_change_id(repo, settings, follower_changes)
    if not targets or not followers:
        return
    tx = _start_transaction(repo, settings)
    tx.move_commits(target_commit_ids=[c.id for c in followers], target_root_ids=[],
                    new_parent_ids=[c.id for c in targets], new_child_ids=[])
    _finish(tx, "parallelize: reconnect descendants", settings, ws, repo)


def _by_change_id(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, change_hexes: Iterable[str]):
    commits: list[pyjj.Commit] = []
    for change_hex in change_hexes:
        commits.extend(repo.revset(settings, change_hex))
    return commits
