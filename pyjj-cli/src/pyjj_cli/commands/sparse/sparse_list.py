"""sparse subcommand: sparse_list."""
import sys

import pyjj
from ..common import (
    _load,
)

def sparse_list(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        patterns = ws.sparse_patterns()
        for p in patterns:
            print(p if p else ".")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
