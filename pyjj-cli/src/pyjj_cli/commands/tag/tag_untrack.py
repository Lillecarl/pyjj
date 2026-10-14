"""tag subcommand: tag_untrack."""

from ..common import (
    _finish,
    _resolve_remote_tags,
    command,
    write_tx,
)


@command
def tag_untrack(args) -> int:
    """`jj tag untrack TAG[@REMOTE]... [--remote REMOTE]`."""
    with write_tx(args) as (settings, ws, repo, tx):
        pairs = _resolve_remote_tags(
            repo, getattr(args, "names", []), getattr(args, "remote", None))
        for tag, remote in pairs:
            tx.git_untrack_remote_tag(remote, tag)
        _finish(tx, f"untrack remote tag {', '.join(getattr(args, 'names', []))}",
                settings, ws, repo)
        return 0
