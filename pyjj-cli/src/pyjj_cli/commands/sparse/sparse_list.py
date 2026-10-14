"""sparse subcommand: sparse_list."""

import pyjj
from ..common import (
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_list(args) -> int:
    _settings, ws, _repo = _load(args)
    patterns = ws.sparse_patterns()
    for p in patterns:
        print(p if p else ".")
    return 0
