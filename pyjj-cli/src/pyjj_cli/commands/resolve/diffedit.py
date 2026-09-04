"""resolve subcommand: diffedit."""
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

def diffedit(args) -> int:
    """`jj diffedit --from X --to Y`: edit the diff between two revisions;
    the result is applied to the destination side."""
    try:
        settings, ws, repo = _load(args)
        if not args.tool:
            print("Error: no diff editor specified; pass --tool",
                  file=sys.stderr)
            return 2
        from_commit = _resolve_one(repo, settings, args.from_)
        to_commit = _resolve_one(repo, settings, args.into)

        changed = _changed_files(repo, settings, from_commit, to_commit)
        before = {p: b for p, (b, _a) in changed.items()}
        after = {p: a for p, (_b, a) in changed.items()}
        if not changed:
            print("No changes to edit.")
            return 0
        selections = _run_diff_tool(settings, args.tool, before, after)
        if _selection_is_empty(selections, before):
            print("Nothing changed.")
            return 0

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [to_commit])
        builder = tx.edit_commit_tree(to_commit, selections)
        edited = builder.write(repo)
        if to_commit.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, edited.id)
        _finish(
            tx,
            f"edit diff from {from_commit.id.hex()} to {to_commit.id.hex()}",
            settings, ws, repo,
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0
