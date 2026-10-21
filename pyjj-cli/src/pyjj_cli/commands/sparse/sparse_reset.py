"""sparse subcommand: sparse_reset."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import (
    command,
    read_repo,
)
from .update import update_sparse_patterns

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def sparse_reset(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, repo):
        update_sparse_patterns(ws, repo, [""])
        return 0
