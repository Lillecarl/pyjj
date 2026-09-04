"""file subcommand: file_annotate."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _finish,
    _format_timestamp,
    _load,
    _resolve_all,
    _resolve_one,
    _short_id,
    _wc_commit,
)

def file_annotate(args) -> int:
    """`jj file annotate` — which commit last touched each line.

    jj puts four columns before the text: the change id, the author's
    email up to the `@` in eight characters, the committer timestamp,
    and the line number. pyjj-cli printed a twelve-character commit id
    and nothing else, which named a commit the reader cannot address --
    a change id is what jj resolves.
    """
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        lines = commit.annotate(repo, args.path)
        commits: dict[str, object] = {}
        for number, ann in enumerate(lines, start=1):
            key = ann.commit_id.hex()
            origin = commits.get(key)
            if origin is None:
                origin = commits[key] = repo.get_commit(ann.commit_id)
            change = _short_id(
                origin.change_id.reverse_hex(),
                repo.shortest_change_id_prefix_len(origin.change_id, settings),
            )
            local = (origin.author.email or "").split("@")[0][:8]
            stamp = _format_timestamp(origin.committer.timestamp)
            prefix = f"{change} {local:<8} {stamp} {number:>4}: "
            sys.stdout.buffer.write(prefix.encode() + ann.line)
            if not ann.line.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
