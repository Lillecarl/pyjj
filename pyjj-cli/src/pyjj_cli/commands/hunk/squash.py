"""hunk subcommand: hunk_squash."""
import sys

import pyjj.hunk as hunk_mod
from ..common import (
    _finish,
    _resolve_one,
    _rev,
    command,
    write_tx,
)
from .helpers import _hunk_spec


@command(catch=(ValueError,))
def hunk_squash(args) -> int:
    """`pyjj hunk squash [-r REV] <spec>` — squash selected hunks into parent."""
    with write_tx(args) as (settings, ws, repo, tx):
        resolved = _hunk_spec(args, "hunk squash", require_message=False)
        if resolved is None:
            return 2
        spec, _ = resolved
        target = _resolve_one(repo, settings, _rev(args, "revision"))
        if len(target.parent_ids) != 1:
            print(f"Error: hunk squash needs a commit with one parent; "
                  f"this one has {len(target.parent_ids)}", file=sys.stderr)
            return 1
        overrides = hunk_mod.spec_to_overrides(repo, target, spec)
        if not overrides:
            print("Nothing selected to squash.")
            return 1
        parent = repo.get_commit(target.parent_ids[0])
        builder = tx.squash_edited(target, parent, overrides)
        if builder is None:
            print("Nothing selected to squash.")
            return 1
        builder.write(repo)
        _finish(tx, "squash commit", settings, ws, repo)
        return 0
