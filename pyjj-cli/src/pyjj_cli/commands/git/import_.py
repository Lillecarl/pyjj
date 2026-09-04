"""git subcommand: git_import."""
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

def git_import(args) -> int:
    """`jj git import` — update repo with changes from the underlying Git repo."""
    try:
        settings, ws, repo = _load(args)
        tx = _start_transaction(repo, settings)
        try:
            tx.git_import_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "import git refs", settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
