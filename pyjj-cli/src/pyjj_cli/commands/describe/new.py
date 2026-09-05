"""describe subcommand: new."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _start_transaction,
    _check_rewritable,
    _commit_location,
    _insert_between,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

def new(args) -> int:
    """`jj new [REVSETS]`: create an empty change.

    `-A`/`-B` insert the change into the graph rather than appending it:
    the commits that would have followed the insertion point are rebased
    onto the new change. `--no-edit` creates it without moving `@`.
    """
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    afters = getattr(args, "insert_afters", None) or []
    befores = getattr(args, "insert_befores", None) or []
    # `-o` and `-r` name parents too, so the two lists are one list.
    parents_given = (list(args.parents_pos)
                     + list(getattr(args, "parents_opt", None) or []))

    try:
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

        tx = _start_transaction(repo, settings)
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
        _finish(tx, "new empty commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


