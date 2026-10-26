"""describe subcommand: new."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _check_rewritable,
    _commit_location,
    _finish,
    _insert_between,
    _resolve_in_arg_order,
    _wc_commit,
    command,
    complete_newline,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def new(args: argparse.Namespace) -> int:
    """`jj new [REVSETS]`: create an empty change.

    `-A`/`-B` insert the change into the graph rather than appending it:
    the commits that would have followed the insertion point are rebased
    onto the new change. `--no-edit` creates it without moving `@`.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []
        # `-o` and `-r` name parents too, so the two lists are one list.
        parents_given = (list(args.parents_pos)
                         + list(getattr(args, "parents_opt", None) or []))

        children: list[pyjj.CommitId]
        if afters or befores:
            parents, children = _commit_location(
                repo, settings, [], afters, befores)
        elif parents_given:
            parents = [c.id for c in
                       _resolve_in_arg_order(repo, settings, parents_given)]
            children = []
        else:
            parents = [_wc_commit(repo, ws).id]
            children = []

        # `-A`/`-B` rebase whatever followed the insertion point, so those
        # commits have to be rewritable.
        _check_rewritable(tx, settings, children)
        builder = tx.new_commit(settings, parents)
        if args.message:
            builder = builder.set_description(complete_newline(args.message))
        child = builder.write(repo)
        if children:
            # The commits that followed the insertion point move onto the
            # new change, together with their own descendants.
            _insert_between(tx, repo, parents, children, child.id)
        if not getattr(args, "no_edit", False):
            # `edit`, not `set_wc_commit`: jj abandons the commit the
            # working copy leaves behind when it is empty, undescribed
            # and nothing else points at it. Moving forward onto a
            # child never triggers that -- the child already made the
            # old commit a non-head -- so this only differs when `new`
            # names a revision somewhere else.
            tx.edit(ws.workspace_name, child)
        _finish(tx, "new empty commit", settings, ws, repo, trial=args)
        return 0


