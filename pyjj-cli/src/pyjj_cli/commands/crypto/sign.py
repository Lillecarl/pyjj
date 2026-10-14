"""crypto subcommand: sign."""
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

def sign(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revs = getattr(args, "revisions", None) or ["@"]
        targets = _resolve_all(repo, settings, revs)
        # Signing without a backend would rewrite every commit and
        # attach nothing; jj refuses up front, and so must pyjj.
        try:
            backend = settings.get_string("signing.backend")
        except pyjj.JjError:
            backend = None
        if not backend or backend == "none":
            print("Error: No signing backend configured", file=sys.stderr)
            print("Hint: For configuring a signing backend, see "
                  "https://docs.jj-vcs.dev/latest/config/#commit-signing",
                  file=sys.stderr)
            return 1

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, targets)
        for commit in targets:
            b = tx.rewrite_commit(settings, commit)
            b.set_sign_behavior("force")
            b.write(repo)
        _finish(tx, f"sign {len(targets)} commits", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
