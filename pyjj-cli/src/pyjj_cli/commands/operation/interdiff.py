"""command: interdiff — compare two revisions' diffs, not their contents."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    CommandError,
    _cli_paths,
    _description_diff_bytes,
    _parent_commits,
    _print_diff_files,
    _resolve_one,
    _rev,
    _warn_unmatched_paths,
    read_repo,
    use_color,
)

if TYPE_CHECKING:
    import argparse


def interdiff(args: argparse.Namespace) -> int:
    """`jj interdiff --from A --to B`.

    Answers "how do the changes A makes differ from the changes B
    makes". A plain diff would also include everything that changed
    between the two commits' parents; this leaves that out, because the
    binding rebases A's tree onto B's parents first.
    """
    if getattr(args, "from_", None) is None and getattr(args, "to", None) is None:
        print("Error: --from or --to is required", file=sys.stderr)
        return 2
    try:
        with read_repo(args) as (settings, ws, repo):
            source = _resolve_one(repo, settings, _rev(args, "from_"))
            target = _resolve_one(repo, settings, _rev(args, "to"))
            paths = _cli_paths(ws, getattr(args, "paths", None)) or None
            if paths:
                # The parents count, for a file either side deletes.
                _warn_unmatched_paths(ws, paths, [
                    *_parent_commits(repo, source), source,
                    *_parent_commits(repo, target), target])
            files = repo.interdiff_files([source], target, settings, paths)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    # jj compares the descriptions too, and prints that block first.
    sys.stdout.flush()
    sys.stdout.buffer.write(
        _description_diff_bytes(args, source.description,
                                target.description, use_color(settings))
    )
    sys.stdout.buffer.flush()
    _print_diff_files(args, ws, files, settings)
    return 0
