"""pyjj-cli rewrite command: commit."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _start_transaction,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _wc_commit,
    complete_newline,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def commit(args) -> int:
    """`jj commit`: describe @, then put the selected paths (or all of @'s
    change) into it and create a new working-copy child on top."""
    try:
        settings, ws, repo = _load(args)
        if args.interactive or args.tool:
            print("Error: interactive commit is not supported; pass -m "
                  "(with optional FILESETS)", file=sys.stderr)
            return 2
        wc = _wc_commit(repo, ws)
        description = _description(args, settings, wc)
        tx = _start_transaction(repo, settings)
        if args.paths_pos:
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
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _description(args, settings, wc) -> str:
    """`-m` alone means no editor. `--editor` opens one anyway, seeded
    with whatever `-m` gave, and no `-m` at all opens one seeded with
    the commit's own description."""
    if args.message is None:
        return _run_editor(settings, wc.description)
    text = complete_newline(args.message)
    if getattr(args, "editor", False):
        return _run_editor(settings, text)
    return text


def _remainder(tx, repo, wc, kept):
    """The new working copy. `jj commit` gives it no description --
    unlike `jj split`, which asks for one for each half."""
    return tx.split_remainder(wc, kept).set_description("").write(repo)
