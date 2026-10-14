"""git subcommand: git_import."""
import sys

import pyjj
from ..common import (
    _start_transaction,
    _finish,
    _load,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_import(args) -> int:
    """`jj git import` — update repo with changes from the underlying Git repo."""
    settings, ws, repo = _load(args)
    tx = _start_transaction(repo, settings)
    try:
        tx.git_import_refs()
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    _finish(tx, "import git refs", settings, ws, repo)
    return 0
