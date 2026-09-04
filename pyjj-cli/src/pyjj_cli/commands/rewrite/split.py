"""pyjj-cli rewrite command: split."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _check_rewritable,
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

def split(args) -> int:
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision or "@")

        tx = repo.start_transaction(settings)
        _check_rewritable(tx, settings, [target])
        if args.paths_pos:
            first_builder = tx.split_selected(target, list(args.paths_pos))
        else:
            # The diff-editor path: select changes by editing the right
            # directory. Upstream order applies the diff selection first,
            # then the description.
            if not args.tool:
                print("Error: no diff editor specified; pass --tool",
                      file=sys.stderr)
                return 2
            parent = repo.get_commit(target.parent_ids[0])
            changed = _changed_files(repo, settings, parent, target)
            before = {p: b for p, (b, _a) in changed.items()}
            after = {p: a for p, (_b, a) in changed.items()}
            selections = _run_diff_tool(settings, args.tool, before, after)
            if _selection_is_empty(selections, before):
                print("No changes selected.")
                return 1
            first_builder = tx.split_selected_edited(target, selections)

        if args.message is not None:
            first_description = complete_newline(args.message)
        else:
            # The editor path: the draft template carries the current
            # description past all "JJ:" comments.
            first_description = _run_editor(settings, target.description)

        first = first_builder.set_description(first_description).write(repo)
        parallel = getattr(args, "parallel", False)
        if parallel:
            second = tx.split_remainder_parallel(target, first).write(repo)
            # Whatever followed the split now sits on both halves, first
            # one first -- a merge's parent order is part of its id.
            children = repo.revset(settings, f"children({target.id.hex()})")
            if children:
                tx.move_commits([c.id for c in children], [],
                                [first.id, second.id], [])
        else:
            second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0
