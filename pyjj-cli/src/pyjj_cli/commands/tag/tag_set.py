"""tag subcommand: tag_set."""
import sys

from ..common import (
    _start_transaction,
    _finish,
    _load,
    _resolve_one,
    command,
)

@command
def tag_set(args) -> int:
    settings, ws, repo = _load(args)
    rev = getattr(args, "revision", "@")
    target = _resolve_one(repo, settings, rev)
    # jj refuses to move a tag that already exists unless asked --
    # a tag is meant to stay put, unlike a bookmark.
    names = list(getattr(args, "names", []))
    if not getattr(args, "allow_move", False):
        for name in names:
            if repo.get_tag(name) is not None:
                print(f"Error: Refusing to move tag: {name}", file=sys.stderr)
                print("Hint: Use --allow-move to update existing tags.",
                      file=sys.stderr)
                return 1
    tx = _start_transaction(repo, settings)
    for name in names:
        tx.set_tag(name, target.id)
    _finish(tx, f"set tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
    return 0
