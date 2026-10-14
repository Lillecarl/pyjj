"""operation subcommand: op_revert."""


from ..common import _finish, _restore_what, command, write_tx


@command
def op_revert(args) -> int:
    """`jj op revert [OPERATION]`: undo one operation, keep the rest.

    Not the same as `op restore`, which makes the view *be* a past view
    and discards everything after it. Reverting merges the named
    operation back out, so only its own changes disappear.
    """
    with write_tx(args) as (settings, ws, repo, tx):
        # `@` is jj's name for the current operation; the binding only
        # takes real ids.
        wanted = getattr(args, "operation", None) or "@"
        target = repo.operation if wanted == "@" else repo.load_operation(wanted)
        description = tx.revert_operation(target, _restore_what(args))
        # Not `_restore_view_command`: merging an operation out records
        # rewrites, and `Transaction.commit` asserts they have been
        # rebased. Restoring a view records none, which is why that
        # helper can skip the step.
        _finish(tx, description, settings, ws, repo)
        return 0
