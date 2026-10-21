"""sparse subcommand: sparse_set."""

import pyjj
from ..common import (
    command,
    read_repo,
)
from .update import update_sparse_patterns

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_set(args) -> int:
    with read_repo(args) as (_settings, ws, repo):
        patterns = set()
        if not getattr(args, "clear", False):
            patterns.update(ws.sparse_patterns())
            patterns.difference_update(getattr(args, "removes", None) or [])
        patterns.update(getattr(args, "adds", None) or [])
        update_sparse_patterns(ws, repo, patterns)
        return 0
