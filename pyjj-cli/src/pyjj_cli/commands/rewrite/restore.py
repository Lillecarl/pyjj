"""pyjj-cli rewrite command: restore."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from ..common import (
    _changed_files,
    _check_rewritable,
    _finish,
    _resolve_one,
    _rev,
    _run_diff_tool,
    _selection_is_empty,
    _split_changed,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

    import pyjj


@command
def restore(args: argparse.Namespace) -> int:
    try:
        with write_tx(args) as (settings, ws, repo, tx):
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
                dst = _resolve_one(repo, settings, _rev(args, "into"))
                src = _resolve_one(repo, settings, _rev(args, "from_"))
            else:
                dst = _resolve_one(repo, settings, changes_in or "@")
                src = None

            _check_rewritable(tx, settings, [dst])
            if tool:
                selections = _selected(repo, settings, tool, dst, src)
                if selections is None:
                    print("Nothing changed.", file=sys.stderr)
                    return 0
                builder = tx.edit_commit_tree(dst, selections)
            else:
                builder = tx.restore(src, dst, paths)
            restored = builder.write(repo)
            if dst.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, restored.id)
            _finish(tx, f"restore into commit {dst.id.hex()}", settings, ws, repo,
                    restore_descendants=getattr(args, "restore_descendants", False))
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def _selected(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, tool, dst, src):
    """What the diff editor chose the destination should hold.

    jj puts the destination's current content on the left and the
    source's on the right, so the editor opens with everything already
    restored and the reader takes back whatever should stay. `None`
    means the editor left the destination as it was.
    """
    if src is not None:
        before, after = _split_changed(_changed_files(repo, settings, dst, src))
    else:
        paths = [entry.path for entry in dst.diff_from_parents(repo)]
        after = dst.parent_contents(repo, paths)
        before = {path: (dst.read_file(path) if dst.file_exists(path) else None)
                  for path in paths}
    if not before and not after:
        return None
    selections = _run_diff_tool(settings, tool, before, after)
    return None if _selection_is_empty(selections, before) else selections
