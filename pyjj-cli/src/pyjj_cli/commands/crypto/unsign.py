"""crypto subcommand: unsign."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_all,
)

def unsign(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revs = getattr(args, "revisions", None) or ["@"]
        targets = _resolve_all(repo, settings, revs)
        tx = _start_transaction(repo, settings)
        # jj checks the whole target set before it looks at signatures, so
        # an immutable target is an error even when nothing would have
        # been rewritten.
        _check_rewritable(tx, settings, targets)
        # Rewriting an unsigned commit would change its commit id for
        # nothing, so jj skips it and says so.
        signed = [commit for commit in targets if commit.is_signed]
        if not signed:
            print("Nothing changed.", file=sys.stderr)
            return 0
        for commit in signed:
            b = tx.rewrite_commit(settings, commit)
            b.set_sign_behavior("drop")
            b.write(repo)
        _finish(tx, f"unsign {len(signed)} commits", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
