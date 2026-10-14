"""tag subcommand: tag_untrack."""

from ..common import (
    _finish,
    _load,
    _resolve_remote_tags,
    _start_transaction,
    command,
)


@command
def tag_untrack(args) -> int:
    """`jj tag untrack TAG[@REMOTE]... [--remote REMOTE]`."""
    settings, ws, repo = _load(args)
    pairs = _resolve_remote_tags(
        repo, getattr(args, "names", []), getattr(args, "remote", None))
    tx = _start_transaction(repo, settings)
    for tag, remote in pairs:
        tx.git_untrack_remote_tag(remote, tag)
    _finish(tx, f"untrack remote tag {', '.join(getattr(args, 'names', []))}",
            settings, ws, repo)
    return 0
