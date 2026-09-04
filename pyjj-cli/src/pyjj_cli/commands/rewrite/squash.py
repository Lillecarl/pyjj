"""pyjj-cli rewrite command: squash."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _wc_commit,
    complete_newline,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def squash(args) -> int:
    try:
        settings, ws, repo = _load(args)
        sources = _resolve_all(repo, settings, list(args.from_ or []) + list(args.revision or []))
        if not sources:
            sources = [_wc_commit(repo, ws)]
        if len(sources) != 1:
            raise CommandError("squashing multiple source revisions is not supported yet")
        source = sources[0]
        dest = (
            _resolve_one(repo, settings, args.into)
            if args.into
            else repo.get_commit(source.parent_ids[0])
        )

        # Message handling, mirroring the real CLI's paths. -u keeps the
        # destination's description untouched; -m replaces; with no flag,
        # a single non-empty side wins, two non-empty sides open the
        # combining editor whose template is destination-block-first.
        use_dest_desc = args.use_destination_message and args.message is None
        if args.message is not None:
            description = complete_newline(args.message)
        else:
            candidates = [c.description for c in [source, dest] if c.description]
            if len(candidates) == 1:
                description = candidates[0]
            elif len(candidates) == 0:
                description = ""
            elif args.use_destination_message:
                pass
            else:
                combined = (
                    "JJ: Description from the destination commit:\n"
                    + dest.description
                    + "\nJJ: Description from source commit:\n"
                    + source.description
                )
                description = _run_editor(settings, combined)

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [source, dest])
        paths = getattr(args, "filesets", None) or None
        # Normalize empty list to None (means all paths)
        if paths == []:
            paths = None
        builder = tx.squash(source, dest, paths=paths,
                            keep_emptied=getattr(args, "keep_emptied", False))
        if builder is None:
            print("Nothing changed.")
            return 0
        if not use_dest_desc:
            builder = builder.set_description(description)
        builder.write(repo)
        _finish(tx, "squash commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
