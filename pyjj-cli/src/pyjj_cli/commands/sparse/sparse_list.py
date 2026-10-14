"""sparse subcommand: sparse_list."""

import pyjj
from ..common import (
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_list(args) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        patterns = ws.sparse_patterns()
        for p in patterns:
            print(p if p else ".")
        return 0
