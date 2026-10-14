"""git subcommand: git_import."""
import sys

import pyjj
from ..common import (
    _finish,
    command,
    write_tx,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_import(args) -> int:
    """`jj git import` — update repo with changes from the underlying Git repo."""
    with write_tx(args) as (settings, ws, repo, tx):
        try:
            tx.git_import_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "import git refs", settings, ws, repo)
        return 0
