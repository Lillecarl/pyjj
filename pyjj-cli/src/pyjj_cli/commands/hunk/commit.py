"""hunk subcommand: hunk_commit."""
import pyjj.hunk as hunk_mod
from ..common import (
    _finish,
    _wc_commit,
    complete_newline,
    command,
    write_tx,
)
from .helpers import _hunk_spec

@command(catch=(ValueError,))
def hunk_commit(args) -> int:
    """`pyjj hunk commit <spec> <message>` — commit selected hunks from working copy."""
    with write_tx(args) as (settings, ws, repo, tx):
        resolved = _hunk_spec(args, "hunk commit", require_message=True)
        if resolved is None:
            return 2
        spec, message = resolved
        # For commit, the target is the working copy commit
        target = _wc_commit(repo, ws)
        # Collect file contents for working copy changes? For commit, we need to snapshot working copy
        # The working copy's changes are not yet in a commit; we need to use the working copy's file contents
        # For now, we treat the working copy's parent as the base, similar to split
        # Use the same spec_to_overrides but for the working copy's diff against parent
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        # For commit, we want to keep selected changes in the current commit, and leave the rest in a new child
        # This is the same as split, but the current commit is the working copy
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"commit {target.id.hex()}", settings, ws, repo)
        return 0
