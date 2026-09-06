"""pyjj-cli rewrite command: restore."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_one,
)


def restore(args) -> int:
    try:
        settings, ws, repo = _load(args)
        changes_in = getattr(args, "changes_in", None)
        if changes_in and (args.from_ or args.into):
            print("Error: --changes-in cannot be used with --from or --into",
                  file=sys.stderr)
            return 2
        paths = list(args.paths_pos) or None

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
        builder = tx.restore(src, dst, paths)
        restored = builder.write(repo)
        if dst.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, restored.id)
        _finish(tx, f"restore into commit {dst.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
