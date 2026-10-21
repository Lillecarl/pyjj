"""sparse subcommand: sparse_reset."""

import pyjj
from ..common import (
    command,
    read_repo,
)
from .update import update_sparse_patterns

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_reset(args) -> int:
    with read_repo(args) as (_settings, ws, repo):
        update_sparse_patterns(ws, repo, [""])
        return 0
