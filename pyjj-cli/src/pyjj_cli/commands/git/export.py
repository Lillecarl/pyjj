"""git subcommand: git_export."""
import sys

import pyjj
from ..common import (
    _finish,
    command,
    write_tx,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_export(args) -> int:
    """`jj git export` — update the underlying Git repo with changes from the repo."""
    with write_tx(args) as (settings, ws, repo, tx):
        try:
            tx.git_export_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "export git refs", settings, ws, repo)
        return 0
