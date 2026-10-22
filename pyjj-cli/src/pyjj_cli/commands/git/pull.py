"""git subcommand: git_pull."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _finish,
    _wc_commit,
    command,
    write_tx,
)
from .fetch import _remotes

if TYPE_CHECKING:
    import argparse


def _short(commit_id: pyjj.CommitId) -> str:
    return commit_id.hex()[:12]


@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_pull(args: argparse.Namespace) -> int:
    """Fetch, then move an idle working copy onto the bookmark it sat under.

    The working copy follows when it is an empty, undescribed commit on
    top of bookmarks that the fetch moved forward. Anything else is left
    alone and the reason is printed: the fetch itself is kept either way.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        wc = _wc_commit(repo, ws)
        before = {bookmark.name: bookmark for bookmark in repo.bookmarks()}

        remotes = _remotes(repo, settings, args)
        for remote in remotes:
            tx.git_fetch(settings, remote, getattr(args, "branches", None), None)

        refusal = None
        advance = None
        names = ""
        parents = wc.parent_ids
        under = [name for name, bookmark in before.items()
                 if bookmark.target_ids == parents and len(parents) == 1]
        after = {bookmark.name: bookmark for bookmark in tx.bookmarks()}

        if len(parents) != 1:
            refusal = "the working copy is a merge, so no bookmark is checked out"
        elif not under:
            refusal = (f"the working copy sits on {_short(parents[0])}, which "
                       "no local bookmark points at")
        else:
            parent = parents[0]
            targets: dict[str, list[str]] = {}
            for name in under:
                now = after.get(name)
                if now is None:
                    refusal = f"bookmark {name} is gone after the fetch"
                elif now.has_conflict:
                    refusal = (f"bookmark {name} is conflicted: local and "
                               "remote both moved it")
                elif now.target_ids == parents:
                    continue
                elif not tx.revset(settings, f"{parent.hex()} & ::{now.target_ids[0].hex()}"):
                    refusal = (f"bookmark {name} moved to {_short(now.target_ids[0])}, "
                               "which does not descend from the working copy's parent "
                               "(not a fast-forward)")
                else:
                    targets.setdefault(now.target_ids[0].hex(), []).append(name)
                if refusal:
                    break

            if refusal is None and len(targets) > 1:
                refusal = ("bookmarks on the working copy's parent moved to "
                           "different commits: "
                           + "; ".join(f"{', '.join(names)} -> {hexid[:12]}"
                                       for hexid, names in targets.items()))
            elif refusal is None and targets:
                if not wc.is_discardable(repo):
                    refusal = ("the working copy holds changes or a description, so "
                               "it is not moved; rebase it with `pyjj rebase -b @ -d "
                               f"{next(iter(targets.values()))[0]}`")
                else:
                    advance = next(iter(targets))
                    names = ", ".join(next(iter(targets.values())))

        if advance is not None:
            child = tx.new_commit(settings, [pyjj.CommitId(advance)]).write(repo)
            # `edit` abandons the old working-copy commit, which is empty
            # and undescribed.
            tx.edit(ws.workspace_name, child)
            _finish(tx, f"pull from git remote(s) {','.join(remotes)}", settings, ws, repo)
            print(f"Fast-forwarded {names} to {advance[:12]}; "
                  f"new working-copy commit {_short(child.id)}", file=sys.stderr)
            return 0

        _finish(tx, f"fetch from git remote(s) {','.join(remotes)}", settings, ws, repo)
        if refusal is None:
            print("Already up to date.", file=sys.stderr)
            return 0
        print(f"Error: fetched, but cannot pull: {refusal}", file=sys.stderr)
        return 1
