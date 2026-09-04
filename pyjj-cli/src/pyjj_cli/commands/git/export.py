"""git subcommand: git_export."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
)

def git_export(args) -> int:
    """`jj git export` — update the underlying Git repo with changes from the repo."""
    try:
        settings, ws, repo = _load(args)
        tx = _start_transaction(repo, settings)
        try:
            tx.git_export_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "export git refs", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
