"""pyjj-cli rewrite command: commit."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from ..common import (
    _changed_files,
    _finish,
    _run_diff_tool,
    _run_editor,
    _split_changed,
    _wc_commit,
    command,
    complete_newline,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

    import pyjj

@command
def commit(args: argparse.Namespace) -> int:
    """`jj commit`: describe @, then put the selected paths (or all of @'s
    change) into it and create a new working-copy child on top."""
    try:
        with write_tx(args) as (settings, ws, repo, tx):
            tool = getattr(args, "tool", None)
            if args.interactive and not tool:
                print("Error: no diff editor specified; pass --tool",
                      file=sys.stderr)
                return 2
            if tool and args.paths_pos:
                # jj shows the editor only the matched paths and leaves the
                # rest of the commit alone. Doing that here needs jj's
                # fileset matcher on the Python side, which pyjj-cli does
                # not have yet, so it refuses rather than guessing.
                print("Error: --tool cannot be combined with FILESETS yet",
                      file=sys.stderr)
                return 2
            wc = _wc_commit(repo, ws)
            description = _description(args, settings, wc)
            if tool:
                # The diff editor picks what stays in the commit. Selecting
                # nothing is not an error here: jj leaves an empty commit
                # behind and moves the whole change to the child.
                kept = (
                    tx.split_selected_edited(wc, _selected(repo, settings, tool, wc))
                    .set_description(description)
                    .write(repo)
                )
                child = _remainder(tx, repo, wc, kept)
            elif args.paths_pos:
                # Selected paths stay in @ (same change id); everything else
                # moves to the new child -- the same primitives `split` uses,
                # with the roles reversed.
                kept = (
                    tx.split_selected(wc, list(args.paths_pos))
                    .set_description(description)
                    .write(repo)
                )
                child = _remainder(tx, repo, wc, kept)
            else:
                described = (
                    tx.rewrite_commit(settings, wc)
                    .set_description(description)
                    .write(repo)
                )
                child = tx.new_commit(settings, [described.id]).write(repo)
            tx.set_wc_commit(ws.workspace_name, child.id)
            _finish(tx, f"commit {wc.id.hex()}", settings, ws, repo)
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def _remainder(tx: pyjj.Transaction, repo: pyjj.ReadonlyRepo, wc: pyjj.Commit, kept: pyjj.Commit):
    """The new working copy. `jj commit` gives it no description --
    unlike `jj split`, which asks for one for each half."""
    return tx.split_remainder(wc, kept).set_description("").write(repo)


def _description(args: argparse.Namespace, settings: pyjj.UserSettings, wc: pyjj.Commit) -> str:
    """`-m` alone means no editor. `--editor` opens one anyway, seeded
    with whatever `-m` gave, and no `-m` at all opens one seeded with
    the commit's own description."""
    if args.message is None:
        return _run_editor(settings, wc.description)
    text = complete_newline(args.message)
    if getattr(args, "editor", False):
        return _run_editor(settings, text)
    return text


def _selected(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, tool: str, wc: pyjj.Commit):
    """What the diff editor chose to keep in the commit, per path."""
    parent = repo.get_commit(wc.parent_ids[0])
    before, after = _split_changed(_changed_files(repo, settings, parent, wc))
    return _run_diff_tool(settings, tool, before, after)
