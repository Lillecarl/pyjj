"""bookmark subcommand: bookmark."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    CommandError,
    _finish,
    _formatter,
    _name_matches,
    _print_ref,
    _ref_list_items,
    _resolve_all,
    _resolve_one,
    _resolve_template,
    _sort_ref_items,
    read_repo,
    write_tx,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence


def bookmark(args: argparse.Namespace) -> int:
    """`jj bookmark` dispatch — create/set/delete/forget/list/move/rename."""
    cmd = getattr(args, "bookmark_command", None)
    # list is read-only, no snapshot needed beyond _load
    if cmd == "list":
        try:
            with read_repo(args) as (_settings, ws, repo):
                template = _resolve_template(_settings, ws, args, "bookmark_list")
                items = _ref_list_items(repo, _settings, args, "bookmark")
                _sort_ref_items(repo, _settings, items, args, "bookmark")
                with _formatter(_settings) as fmt:
                    for ref, tracked in items:
                        _print_ref(repo, _settings, ref, template, tracked,
                                   fmt=fmt)
                return 0
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
    if cmd == "create":
        try:
            with write_tx(args) as (settings, ws, repo, tx):
                target = _resolve_one(repo, settings, args.revision)
                for name in args.names:
                    if repo.get_bookmark(name) is not None:
                        raise CommandError(
                            f"Bookmark already exists: {name} "
                            "(use `bookmark set` to move it)"
                        )
                    tx.set_bookmark(name, target.id)
                _finish(tx, f"create bookmark {', '.join(args.names)} "
                            f"pointing to commit {target.id.hex()}",
                        settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "set":
        try:
            with write_tx(args) as (settings, ws, repo, tx):
                target = _resolve_one(repo, settings, args.revision)
                names = list(getattr(args, "names", None) or [])
                # Unlike `move`, this creates a bookmark that is not there
                # yet. What it will not do without `-B` is move an existing
                # one anywhere but forward.
                if not getattr(args, "allow_backwards", False):
                    for name in names:
                        existing = repo.get_bookmark(name)
                        targets: list[pyjj.CommitId] = list(existing.target_ids) if existing else []
                        if not _is_fast_forward(repo, settings, targets, target.id):
                            raise CommandError(
                                "Refusing to move bookmark backwards or "
                                f"sideways: {name}")
                for name in names:
                    tx.set_bookmark(name, target.id)
                _finish(tx, f"point bookmark {', '.join(names)} to commit "
                            f"{target.id.hex()}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd in ("delete", "forget"):
        try:
            with write_tx(args) as (settings, ws, repo, tx):
                if cmd == "forget":
                    include_remotes = bool(getattr(args, "include_remotes", False))
                    remotes_by_name: dict[str, list[str]] = {}
                    for remote_bm in repo.remote_bookmarks():
                        remotes_by_name.setdefault(remote_bm.name, []).append(
                            remote_bm.remote)
                    forgotten_local = 0
                    forgotten_remote = 0
                    matched = []
                    for name in args.names:
                        if repo.get_bookmark(name) is None:
                            print(f"Warning: No such bookmark: {name}", file=sys.stderr)
                            continue
                        tx.delete_bookmark(name)
                        matched.append(name)
                        forgotten_local += 1
                        for remote in remotes_by_name.get(name, []):
                            if include_remotes:
                                tx.remove_remote_bookmark(remote, name)
                                forgotten_remote += 1
                            elif remote != "git":
                                # Plain forget untracks instead of removing;
                                # the git-tracking remote cannot be untracked.
                                tx.git_untrack_remote_bookmark(remote, name)
                    if not matched:
                        print("No bookmarks to forget.")
                        return 0
                    if forgotten_local:
                        print(f"Forgot {forgotten_local} local bookmarks.")
                    if forgotten_remote:
                        print(f"Forgot {forgotten_remote} remote bookmarks.")
                    _finish(tx, f"forget bookmark {', '.join(matched)}",
                            settings, ws, repo)
                    return 0
                matched = []
                for name in args.names:
                    if repo.get_bookmark(name) is None:
                        print(f"Warning: No such bookmark: {name}", file=sys.stderr)
                        continue
                    tx.delete_bookmark(name)
                    matched.append(name)
                # jj names every bookmark it matched, and says which of the
                # two commands ran -- `delete` and `forget` differ.
                _finish(tx, f"{cmd} bookmark {', '.join(matched)}",
                        settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "rename":
        try:
            with write_tx(args) as (settings, ws, repo, tx):
                old_bm = repo.get_bookmark(args.old)
                if old_bm is None:
                    raise CommandError(f"No such bookmark: {args.old}")
                if args.old == args.new:
                    if not getattr(args, "overwrite_existing", False):
                        raise CommandError(f"Bookmark already exists: {args.new}")
                    # Renaming onto itself changes nothing (and records no
                    # operation, like real jj).
                    return 0
                if repo.get_bookmark(args.new) is not None:
                    if not getattr(args, "overwrite_existing", False):
                        raise CommandError(f"Bookmark already exists: {args.new}")
                    # else: fall through and overwrite below.
                if not old_bm.target_ids:
                    raise CommandError(f"Bookmark {args.old} has no target")
                # For conflicted bookmarks, rename is ambiguous; require non-conflicted for now.
                if old_bm.has_conflict:
                    raise CommandError(f"Bookmark {args.old} is conflicted, cannot rename")
                tx.set_bookmark(args.new, old_bm.target_ids[0])
                tx.delete_bookmark(args.old)
                _finish(tx, f"rename bookmark {args.old} to {args.new}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    if cmd == "move":
        try:
            with write_tx(args) as (settings, ws, repo, tx):
                names = list(getattr(args, "names", None) or [])
                froms = list(getattr(args, "from_", None) or [])
                if not names and not froms:
                    print("Error: bookmark move requires bookmark names or --from",
                          file=sys.stderr)
                    return 2
                target = _resolve_one(repo, settings, args.to)
                source_ids = set()
                if froms:
                    source_ids = {c.id.hex()
                                  for c in _resolve_all(repo, settings, froms)}
                to_move = []
                for bookmark in repo.bookmarks():
                    # A name is a pattern, so one argument can move a set.
                    if names and not any(_name_matches(bookmark.name, pattern)
                                         for pattern in names):
                        continue
                    if froms and not any(i.hex() in source_ids
                                         for i in bookmark.target_ids):
                        continue
                    if [i.hex() for i in bookmark.target_ids] == [target.id.hex()]:
                        # Already there. Not an error, and not a move either.
                        continue
                    to_move.append(bookmark)
                if not to_move:
                    if names and any(_name_matches(bookmark.name, pattern)
                                     for bookmark in repo.bookmarks()
                                     for pattern in names):
                        print(f"Already at {target.id.hex()[:12]}.")
                    else:
                        print("No bookmarks to update.")
                    return 0
                if not getattr(args, "allow_backwards", False):
                    for bookmark in to_move:
                        if not _is_fast_forward(repo, settings,
                                                bookmark.target_ids, target.id):
                            raise CommandError(
                                "Refusing to move bookmark backwards or "
                                f"sideways: {bookmark.name}")
                for bookmark in to_move:
                    tx.set_bookmark(bookmark.name, target.id)
                _finish(tx, "point bookmark "
                            f"{', '.join(b.name for b in to_move)} to commit "
                            f"{target.id.hex()}", settings, ws, repo)
                print(f"Moved {', '.join(b.name for b in to_move)} to "
                      f"{target.id.hex()[:12]}")
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    print("usage: pyjj bookmark {create,set,delete,forget,list,move,rename}", file=sys.stderr)
    return 2


def _is_fast_forward(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings,
    old_ids: Sequence[pyjj.CommitId], new_id: pyjj.CommitId,
) -> bool:
    """Whether moving a bookmark from `old_ids` to `new_id` only goes
    forward.

    jj allows the move when *any* old target is an ancestor of the new
    one, so resolving a conflicted bookmark onto one of its own sides
    counts as forward. A bookmark that does not exist yet has nowhere to
    go backwards from.
    """
    if not old_ids:
        return True
    union = " | ".join(i.hex() for i in old_ids)
    return bool(repo.revset(settings, f"({union}) & ::{new_id.hex()}"))
