"""git subcommand: git_import."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _finish,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_import(args: argparse.Namespace) -> int:
    """`jj git import` — update repo with changes from the underlying Git repo."""
    with write_tx(args) as (settings, ws, repo, tx):
        try:
            tx.git_import_refs()
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
            return 1
        _finish(tx, "import git refs", settings, ws, repo)
        return 0
