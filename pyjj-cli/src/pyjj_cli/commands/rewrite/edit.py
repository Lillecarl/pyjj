"""pyjj-cli rewrite command: edit."""

from ..common import (
    _start_transaction,
    _check_rewritable,
    _finish,
    _load,
    _resolve_one,
    command,
)

@command
def edit(args) -> int:
    settings, ws, repo = _load(args)
    target = _resolve_one(
        repo, settings,
        getattr(args, "revision_pos", None)
        or getattr(args, "revision_flags", None))
    tx = _start_transaction(repo, settings)
    _check_rewritable(tx, settings, [target])
    # MutableRepo::edit abandons a discardable, unreferenced old wc
    # itself; rebase_descendants() in _finish clears the pending map.
    tx.edit(ws.workspace_name, target)
    _finish(tx, f"edit commit {target.id.hex()}", settings, ws, repo)
    return 0
