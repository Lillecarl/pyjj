"""command: interdiff — compare two revisions' diffs, not their contents."""
import sys

import pyjj

from ..common import (
    CommandError,
    _description_diff_bytes,
    _load,
    _print_diff_files,
    _resolve_one,
)


def interdiff(args) -> int:
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
        settings, ws, repo = _load(args)
        source = _resolve_one(repo, settings, args.from_ or "@")
        target = _resolve_one(repo, settings, args.to or "@")
        paths = list(getattr(args, "paths", None) or []) or None
        files = repo.interdiff_files(source, target, settings, paths)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    # jj compares the descriptions too, and prints that block first.
    sys.stdout.flush()
    sys.stdout.buffer.write(
        _description_diff_bytes(args, source.description, target.description)
    )
    sys.stdout.buffer.flush()
    _print_diff_files(args, ws, files, settings)
    return 0
