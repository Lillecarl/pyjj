"""`pyjj workflow NAME`: run a workflow a user extension defines.

The workflow gets a `pyjj.Repo` built from this command's own settings,
so the working copy is snapshotted, `--config` applies and the identity
hooks have already picked who commits.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from .common import _load, command

if TYPE_CHECKING:
    import argparse


@command
def workflow(args: argparse.Namespace) -> int:
    error = getattr(args, "_workflow_error", None)
    if error is not None:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    found = pyjj.extensions.workflows()
    if args._workflow is None:
        if not found:
            print("No workflows. List extension files in the `pyjj.extensions` "
                  "config key.", file=sys.stderr)
            return 1
        width = max(map(len, found))
        for name, cls in found.items():
            print(f"{name:<{width}}  {cls.help or ''}".rstrip())
        return 0
    settings, ws, _repo = _load(args)
    repo = pyjj.Repo(ws, settings)
    result = found[args._workflow]().run(repo, args)
    return 0 if result is None else int(result)
