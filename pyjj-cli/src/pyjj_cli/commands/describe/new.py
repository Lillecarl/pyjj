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

    try:
        if afters or befores:
            parents, children = _insertion_point(repo, settings, afters, befores)
        elif args.parents_pos:
            parents = [c.id for c in
                       _resolve_in_arg_order(repo, settings, args.parents_pos)]
            children = []
        else:
            parents = [_wc_commit(repo, ws).id]
            children = []

        tx = repo.start_transaction(settings)
        builder = tx.new_commit(settings, parents)
        if args.message:
            builder = builder.set_description(complete_newline(args.message))
        child = builder.write(repo)
        if children:
            # The commits that followed the insertion point move onto the
            # new change, together with their own descendants.
            tx.move_commits([], children, [child.id], [])
        if not getattr(args, "no_edit", False):
            tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, "new empty commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _insertion_point(repo, settings, afters, befores):
    """Parents for the new change, and the commits to rebase onto it."""
    parents: list = []
    children: list = []
    if afters:
        parents = [c.id for c in _resolve_in_arg_order(repo, settings, afters)]
        expression = " | ".join(f"children({a})" for a in afters)
        children = [c.id for c in repo.revset(settings, expression)]
    if befores:
        before_commits = _resolve_in_arg_order(repo, settings, befores)
        children = [c.id for c in before_commits]
        if not afters:
            seen = {}
            for commit in before_commits:
                for pid in commit.parent_ids:
                    seen[pid.hex()] = pid
            parents = list(seen.values())
    return parents, children
