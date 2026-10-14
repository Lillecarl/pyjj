"""tag subcommand: tag_delete."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _finish,
    _load,
)

def tag_delete(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = _start_transaction(repo, settings)
        for name in getattr(args, "names", []):
            if repo.get_tag(name) is None:
                print(f"Warning: No such tag: {name}", file=sys.stderr)
                continue
            tx.delete_tag(name)
        _finish(tx, f"delete tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
