"""crypto subcommand: unsign."""
import sys

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_all,
    command,
    write_tx,
)

@command
def unsign(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        revs = getattr(args, "revisions", None) or ["@"]
        targets = _resolve_all(repo, settings, revs)
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
