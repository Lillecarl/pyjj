"""resolve subcommand: resolve."""
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

def resolve(args) -> int:
    """`jj resolve [-r REV] [--tool NAME] [FILESETS]`: run a 3-way merge
    tool per conflicted file. Mirrors upstream ordering: conflict listing
    and tool runs happen before any mutation (an aborted tool leaves no
    operation), the commit is rewritten even when nothing resolved, and
    leftover conflicts are reported as an error AFTER the operation
    commits."""
    try:
        settings, ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)

        candidates = commit.list_files(list(args.paths_pos) or None)
        conflicts = []
        for p in candidates:
            try:
                commit.read_file(p)
            except pyjj.JjError:
                conflicts.append(p)
        conflicts.sort()
        if not conflicts:
            if args.paths_pos:
                print("Error: No conflicts found at the given path(s)",
                      file=sys.stderr)
            else:
                print("Error: No conflicts found at this revision",
                      file=sys.stderr)
            return 1

        if args.list_:
            for p in conflicts:
                print(p)
            return 0

        if not args.tool:
            print("Error: no merge tool specified; pass --tool",
                  file=sys.stderr)
            return 2

        # Built-in side-picking tools: no external process, no merge-args.
        if args.tool in (":ours", ":theirs"):
            side = 0 if args.tool == ":ours" else 1
            tx = repo.start_transaction(settings)
            builder = tx.pick_conflict_sides(commit, conflicts, side)
            new_commit = builder.write(repo)
            if commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, new_commit.id)
            _finish(tx, f"Resolve conflicts in commit {commit.id.hex()}",
                    settings, ws, repo)
        else:
            edits_markers = bool(
                settings.get_bool(
                    f"merge-tools.{args.tool}.merge-tool-edits-conflict-markers"
                )
            )

            resolutions: dict[str, bytes] = {}
            for p in conflicts:
                sides = dict(commit.conflict_sides(p))
                materialized = commit.materialize_conflict(settings, p)
                out = _run_merge_tool(settings, args.tool, sides, p,
                                      edits_markers, bytes(materialized))
                initial = bytes(materialized) if edits_markers else b""
                if not out or out == initial:
                    # Upstream's EmptyOrUnchanged: leave this path conflicted
                    # and keep going with the remaining files.
                    continue
                resolutions[p] = out

            tx = repo.start_transaction(settings)
            if resolutions:
                builder = tx.resolve_conflicts(commit, resolutions)
            else:
                # Nothing changed, but real jj still rewrites the commit
                # (committer-timestamp bump) and records the operation.
                builder = tx.rewrite_commit(commit)
            new_commit = builder.write(repo)
            if commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, new_commit.id)
            _finish(tx, f"Resolve conflicts in commit {commit.id.hex()}",
                    settings, ws, repo)

        unresolved = []
        for p in conflicts:
            try:
                new_commit.read_file(p)
            except pyjj.JjError:
                unresolved.append(p)
        if unresolved:
            print("Warning: Some files at this revision still have "
                  "conflicts:", file=sys.stderr)
            for p in unresolved:
                print(f"  {p}", file=sys.stderr)
            return 1
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
