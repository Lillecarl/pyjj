"""bookmark subcommand: bookmark."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _print_ref,
    _resolve_template,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

def bookmark(args) -> int:
    """`jj bookmark` dispatch — create/set/delete/forget/list/move/rename."""
    cmd = getattr(args, "bookmark_command", None)
    # list is read-only, no snapshot needed beyond _load
    if cmd == "list":
        try:
            _settings, ws, repo = _load(args)
            template = _resolve_template(_settings, ws, args, "bookmark_list")
            names = getattr(args, "names", None) or []
            bms = repo.bookmarks()
            # Filter by names if given (exact match for now)
            if names:
                bms = [b for b in bms if b.name in names]
            for bm in sorted(bms, key=lambda b: b.name):
                _print_ref(repo, _settings, bm, template)
            return 0
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
    if cmd == "create":
        try:
            settings, ws, repo = _load(args)
            target = _resolve_one(repo, settings, args.revision)
            tx = repo.start_transaction(settings)
            for name in args.names:
                if repo.get_bookmark(name) is not None:
                    raise CommandError(
                        f"Bookmark already exists: {name} "
                        "(use `bookmark set` to move it)"
                    )
                tx.set_bookmark(name, target.id)
            _finish(tx, f"point bookmark at {target.id.hex()}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "set":
        try:
            settings, ws, repo = _load(args)
            target = _resolve_one(repo, settings, args.revision)
            if repo.get_bookmark(args.name) is None:
                raise CommandError(f"No such bookmark: {args.name}")
            tx = repo.start_transaction(settings)
            tx.set_bookmark(args.name, target.id)
            _finish(tx, f"point bookmark at {target.id.hex()}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd in ("delete", "forget"):
        try:
            settings, ws, repo = _load(args)
            tx = repo.start_transaction(settings)
            for name in args.names:
                if repo.get_bookmark(name) is None:
                    print(f"Warning: No such bookmark: {name}", file=sys.stderr)
                    continue
                tx.delete_bookmark(name)
            _finish(tx, f"delete bookmark {args.names[0]}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "rename":
        try:
            settings, ws, repo = _load(args)
            old_bm = repo.get_bookmark(args.old)
            if old_bm is None:
                raise CommandError(f"No such bookmark: {args.old}")
            if repo.get_bookmark(args.new) is not None:
                raise CommandError(f"Bookmark already exists: {args.new}")
            if not old_bm.target_ids:
                raise CommandError(f"Bookmark {args.old} has no target")
            # For conflicted bookmarks, rename is ambiguous; require non-conflicted for now.
            if old_bm.has_conflict:
                raise CommandError(f"Bookmark {args.old} is conflicted, cannot rename")
            tx = repo.start_transaction(settings)
            tx.set_bookmark(args.new, old_bm.target_ids[0])
            tx.delete_bookmark(args.old)
            _finish(tx, f"rename bookmark {args.old} to {args.new}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "move":
        try:
            settings, ws, repo = _load(args)
            target = _resolve_one(repo, settings, args.to)
            # Simple move: named bookmarks to target. --from filtering.
            names = getattr(args, "names", None) or []
            if args.from_:
                # --from mode: move bookmarks pointing at those revisions
                sources = _resolve_all(repo, settings, [args.from_])
                source_ids = {c.id.hex() for c in sources}
                if names:
                    to_move = []
                    for n in names:
                        bm = repo.get_bookmark(n)
                        if bm and bm.target_ids and bm.target_ids[0].hex() in source_ids:
                            to_move.append(n)
                else:
                    to_move = [bm.name for bm in repo.bookmarks() if bm.target_ids and bm.target_ids[0].hex() in source_ids]
            else:
                to_move = names
                if not to_move:
                    print("Error: bookmark move requires bookmark names or --from", file=sys.stderr)
                    return 2
            tx = repo.start_transaction(settings)
            for name in to_move:
                if repo.get_bookmark(name) is None:
                    raise CommandError(f"No such bookmark: {name}")
                tx.set_bookmark(name, target.id)
            _finish(tx, f"move bookmarks to {target.id.hex()}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    print(f"usage: pyjj bookmark {{create,set,delete,forget,list,move,rename}}", file=sys.stderr)
    return 2
