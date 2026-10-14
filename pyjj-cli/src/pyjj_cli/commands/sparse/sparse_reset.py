"""sparse subcommand: sparse_reset."""

import pyjj
from ..common import (
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_reset(args) -> int:
    _settings, ws, _repo = _load(args)
    ws.set_sparse_patterns([""])
    return 0
