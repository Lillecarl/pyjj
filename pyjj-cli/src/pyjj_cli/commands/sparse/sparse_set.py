"""sparse subcommand: sparse_set."""

import pyjj
from ..common import (
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_set(args) -> int:
    _settings, ws, _repo = _load(args)
    # Get current patterns
    current = ws.sparse_patterns()
    # Handle --clear
    if getattr(args, "clear", False):
        new_patterns: list[str] = []
    else:
        new_patterns = list(current)
    adds = getattr(args, "adds", None) or []
    removes = getattr(args, "removes", None) or []
    for pat in adds:
        if pat not in new_patterns:
            new_patterns.append(pat)
    for pat in removes:
        if pat in new_patterns:
            new_patterns.remove(pat)
    # If after clear and no adds, it means empty sparse (no files) — but jj would keep at least?
    # For reset, we use [""] — for set with --clear and no adds, we set to []
    if not new_patterns and not getattr(args, "clear", False):
        # No change, just list
        for p in current:
            print(p if p else ".")
        return 0
    ws.set_sparse_patterns(new_patterns)
    return 0
