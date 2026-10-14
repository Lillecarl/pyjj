"""bookmark subcommand: bookmark_untrack."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _finish,
    _load,
    _split_remote_ref,
)

def bookmark_untrack(args) -> int:
    try:
        settings, ws, repo = _load(args)
        default_remote = getattr(args, "remote", None)
        tx = _start_transaction(repo, settings)
        for name in getattr(args, "names", []):
            bookmark, remote = _split_remote_ref(name, default_remote)
            tx.git_untrack_remote_bookmark(remote, bookmark)
        _finish(tx, f"untrack remote bookmark {', '.join(getattr(args, 'names', []))}",
                settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
