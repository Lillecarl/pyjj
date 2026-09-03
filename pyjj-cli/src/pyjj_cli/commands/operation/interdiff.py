"""command: interdiff — compare two revisions' diffs, not their contents."""
import sys

import pyjj

from ..common import CommandError, _load, _resolve_one


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
        settings, _ws, repo = _load(args)
        source = _resolve_one(repo, settings, args.from_ or "@")
        target = _resolve_one(repo, settings, args.to or "@")
        paths = list(getattr(args, "paths", None) or []) or None
        entries = repo.interdiff(source, target, paths)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    for entry in entries:
        print(f"{entry.status:8} {entry.path}")
    return 0
