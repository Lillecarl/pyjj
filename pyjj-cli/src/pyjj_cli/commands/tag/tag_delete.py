"""tag subcommand: tag_delete."""
import sys

from ..common import (
    _start_transaction,
    _finish,
    _load,
    command,
)

@command
def tag_delete(args) -> int:
    settings, ws, repo = _load(args)
    tx = _start_transaction(repo, settings)
    for name in getattr(args, "names", []):
        if repo.get_tag(name) is None:
            print(f"Warning: No such tag: {name}", file=sys.stderr)
            continue
        tx.delete_tag(name)
    _finish(tx, f"delete tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
    return 0
