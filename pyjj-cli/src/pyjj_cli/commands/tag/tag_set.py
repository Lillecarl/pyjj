"""tag subcommand: tag_set."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    _finish,
    _resolve_one,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def tag_set(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
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
        for name in names:
            tx.set_tag(name, target.id)
        _finish(tx, f"set tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
