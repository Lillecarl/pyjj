"""tag subcommand: tag_untrack."""
import sys

import pyjj
from ..common import (
    _finish,
    _load,
    _resolve_remote_tags,
    _start_transaction,
    CommandError,
)


def tag_untrack(args) -> int:
    """`jj tag untrack TAG[@REMOTE]... [--remote REMOTE]`."""
    try:
        settings, ws, repo = _load(args)
        pairs = _resolve_remote_tags(
            repo, getattr(args, "names", []), getattr(args, "remote", None))
        tx = _start_transaction(repo, settings)
        for tag, remote in pairs:
            tx.git_untrack_remote_tag(remote, tag)
        _finish(tx, f"untrack remote tag {', '.join(getattr(args, 'names', []))}",
                settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
