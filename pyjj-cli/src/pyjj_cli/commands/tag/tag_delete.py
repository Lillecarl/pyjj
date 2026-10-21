"""tag subcommand: tag_delete."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ..common import (
    _finish,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def tag_delete(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        for name in getattr(args, "names", []):
            if repo.get_tag(name) is None:
                print(f"Warning: No such tag: {name}", file=sys.stderr)
                continue
            tx.delete_tag(name)
        _finish(tx, f"delete tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
