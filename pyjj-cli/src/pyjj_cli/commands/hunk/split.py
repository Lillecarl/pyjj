"""hunk subcommand: hunk_split."""
import pyjj.hunk as hunk_mod
from ..common import (
    _finish,
    _resolve_one,
    _rev,
    complete_newline,
    command,
    write_tx,
)
from .helpers import _hunk_spec

@command(catch=(ValueError,))
def hunk_split(args) -> int:
    """`pyjj hunk split [-r REV] <spec> <message>` — split with hunk/line spec."""
    with write_tx(args) as (settings, ws, repo, tx):
        resolved = _hunk_spec(args, "hunk split", require_message=True)
        if resolved is None:
            return 2
        spec, message = resolved
        target = _resolve_one(repo, settings, _rev(args, "revision"))
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        # Use split_selected_edited with overrides
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
        return 0
