"""pyjj-cli rewrite command: restore."""
import subprocess
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_one,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
)


def restore(args) -> int:
    try:
        settings, ws, repo = _load(args)
        changes_in = getattr(args, "changes_in", None)
        if changes_in and (args.from_ or args.into):
            print("Error: --changes-in cannot be used with --from or --into",
                  file=sys.stderr)
            return 2
        tool = getattr(args, "tool", None)
        paths = list(args.paths_pos) or None
        if tool and paths:
            # jj shows the editor only the matched paths and leaves the
            # rest of the destination alone. Doing that here needs jj's
            # fileset matcher on the Python side, which pyjj-cli does
            # not have yet, so it refuses rather than guessing.
            print("Error: --tool cannot be combined with FILESETS yet",
                  file=sys.stderr)
            return 2

        # Naming either side defaults the other to `@`. Naming neither
        # restores `@` -- or `--changes-in`'s revision -- from the merge
        # of its own parents, which is what makes a bare `jj restore`
        # undo the working copy.
        if args.from_ or args.into:
            dst = _resolve_one(repo, settings, args.into or "@")
            src = _resolve_one(repo, settings, args.from_ or "@")
        else:
            dst = _resolve_one(repo, settings, changes_in or "@")
            src = None

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [dst])
        if tool:
            selections = _selected(repo, settings, tool, dst, src)
            if selections is None:
                print("Nothing changed.")
                return 0
            builder = tx.edit_commit_tree(dst, selections)
        else:
            builder = tx.restore(src, dst, paths)
        restored = builder.write(repo)
        if dst.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, restored.id)
        _finish(tx, f"restore into commit {dst.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def _selected(repo, settings, tool, dst, src):
    """What the diff editor chose the destination should hold.

    jj puts the destination's current content on the left and the
    source's on the right, so the editor opens with everything already
    restored and the reader takes back whatever should stay. `None`
    means the editor left the destination as it was.
    """
    if src is not None:
        changed = _changed_files(repo, settings, dst, src)
        before = {path: b for path, (b, _a) in changed.items()}
        after = {path: a for path, (_b, a) in changed.items()}
    else:
        paths = [entry.path for entry in dst.diff_from_parents(repo)]
        after = dst.parent_contents(repo, paths)
        before = {path: (dst.read_file(path) if dst.file_exists(path) else None)
                  for path in paths}
    if not before and not after:
        return None
    selections = _run_diff_tool(settings, tool, before, after)
    return None if _selection_is_empty(selections, before) else selections
