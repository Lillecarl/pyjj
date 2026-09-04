"""operation subcommand: op_revert."""
import sys

import pyjj

from ..common import CommandError, _finish, _load, _start_transaction


def op_revert(args) -> int:
    """`jj op revert [OPERATION]`: undo one operation, keep the rest.

    Not the same as `op restore`, which makes the view *be* a past view
    and discards everything after it. Reverting merges the named
    operation back out, so only its own changes disappear.
    """
    try:
        settings, ws, repo = _load(args)
        # `@` is jj's name for the current operation; the binding only
        # takes real ids.
        wanted = getattr(args, "operation", None) or "@"
        target = repo.operation if wanted == "@" else repo.load_operation(wanted)
        tx = _start_transaction(repo, settings)
        description = tx.revert_operation(target)
        # Not `_restore_view_command`: merging an operation out records
        # rewrites, and `Transaction.commit` asserts they have been
        # rebased. Restoring a view records none, which is why that
        # helper can skip the step.
        _finish(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    return 0
