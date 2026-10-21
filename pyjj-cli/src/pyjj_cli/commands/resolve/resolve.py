"""resolve subcommand: resolve."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_one,
    _run_merge_tool,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

_EMPTY_OR_UNCHANGED = (
    "The output file is either unchanged or empty after the editor quit "
    "(run with --debug to see the exact invocation).")


@command
def resolve(args: argparse.Namespace) -> int:
    """`jj resolve [-r REV] [--tool NAME] [FILESETS]`: run a 3-way merge
    tool per conflicted file. Mirrors upstream ordering: conflict listing
    and tool runs happen before any mutation (an aborted tool leaves no
    operation). A file the tool leaves empty or unchanged stops the run:
    the first file aborts it with nothing written, a later one keeps the
    files resolved so far and fails after the operation commits."""
    with write_tx(args) as (settings, ws, repo, tx):
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
            _check_rewritable(tx, settings, [commit])
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
            stopped = False
            for p in conflicts:
                sides = dict(commit.conflict_sides(p))
                materialized = commit.materialize_conflict(settings, p)
                out = _run_merge_tool(settings, args.tool, sides, p,
                                      edits_markers, bytes(materialized))
                initial = bytes(materialized) if edits_markers else b""
                if not out or out == initial:
                    if not resolutions:
                        print(f"Error: {_EMPTY_OR_UNCHANGED}", file=sys.stderr)
                        return 1
                    stopped = True
                    break
                resolutions[p] = out

            _check_rewritable(tx, settings, [commit])
            new_commit = tx.resolve_conflicts(commit, resolutions).write(repo)
            if commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, new_commit.id)
            _finish(tx, f"Resolve conflicts in commit {commit.id.hex()}",
                    settings, ws, repo)
            if stopped:
                print(f"Error: Stopped due to error after resolving "
                      f"{len(resolutions)} conflicts", file=sys.stderr)
                print(f"Caused by: {_EMPTY_OR_UNCHANGED}", file=sys.stderr)
                return 1

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
        return 0
