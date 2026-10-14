"""sparse subcommand: sparse_reset."""

import pyjj
from ..common import (
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_reset(args) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        ws.set_sparse_patterns([""])
        return 0
