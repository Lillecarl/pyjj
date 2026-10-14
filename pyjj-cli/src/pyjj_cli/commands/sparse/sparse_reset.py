"""sparse subcommand: sparse_reset."""
import sys

import pyjj
from ..common import (
    _load,
)

def sparse_reset(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        ws.set_sparse_patterns([""])
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
