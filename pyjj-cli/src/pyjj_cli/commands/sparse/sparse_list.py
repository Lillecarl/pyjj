"""sparse subcommand: sparse_list."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_list(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        patterns = ws.sparse_patterns()
        for p in patterns:
            print(p if p else ".")
        return 0
