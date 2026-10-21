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
        target = _wc_commit(repo, ws)
        overrides = hunk_mod.spec_to_overrides(repo, target, spec)
        if not overrides:
            print("No changes selected.")
            return 1
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"commit {target.id.hex()}", settings, ws, repo)
        return 0
