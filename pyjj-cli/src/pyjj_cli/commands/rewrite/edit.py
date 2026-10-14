"""pyjj-cli rewrite command: edit."""

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_one,
    command,
    write_tx,
)

@command
def edit(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        target = _resolve_one(
            repo, settings,
            getattr(args, "revision_pos", None)
            or getattr(args, "revision_flags", None))
        _check_rewritable(tx, settings, [target])
        # MutableRepo::edit abandons a discardable, unreferenced old wc
        # itself; rebase_descendants() in _finish clears the pending map.
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"edit commit {target.id.hex()}", settings, ws, repo)
        return 0
