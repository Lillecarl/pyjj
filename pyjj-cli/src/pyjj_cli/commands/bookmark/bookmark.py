"""bookmark subcommand: bookmark."""
import fnmatch
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
    _start_transaction,
    _formatter,
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


class _DeletedBookmark:
    """A bookmark whose local target is gone but whose remotes remain.

    `repo.bookmarks()` lists the bookmarks that are present, so a name
    that survives on a remote alone has nothing to stand for it. jj
    still heads the item with `name (deleted)`.
    """

    has_conflict = False
    removed_ids = ()
    target_ids = ()

    def __init__(self, name: str) -> None:
        self.name = name


def _list_items(repo, args):
    """The items `jj bookmark list` prints, in jj's order.

    This is `collect_items` from jj's `cli/src/commit_ref_list.rs`,
    driven by the same three predicates its `bookmark list` builds:

      * a local ref appears on its own only without `--tracked` and
        without `--remote`;
      * a tracked remote ref appears only when its target differs from
        the local one, unless `--tracked`, `--all-remotes` or
        `--remote` asks for the synced ones too;
      * an untracked remote ref appears as an item of its own under
        `--all-remotes` or `--remote`, never under `--tracked`.

    A name with no local ref still heads an item when a tracked remote
    survives under it, which is how a deleted bookmark stays visible.

    Items sort by name. jj sorts the whole list, and its sort is
    stable, so a name's own item comes before the untracked remotes
    that share its name.
    """
    all_remotes = getattr(args, "all_remotes", False)
    tracked_only = getattr(args, "tracked", False)
    patterns = getattr(args, "remotes", None)

    include_local_only = not tracked_only and patterns is None
    include_synced = tracked_only or all_remotes or patterns is not None
    include_untracked = not tracked_only and (all_remotes or patterns is not None)

    def matches(remote: str) -> bool:
        if patterns is not None:
            return any(fnmatch.fnmatchcase(remote, p) for p in patterns)
        # `--tracked` on its own means `--remote=~git`: the local
        # Git-tracking remote is noise in a listing about remotes.
        return not (tracked_only and remote == "git")

    def synced(local, remote_ref) -> bool:
        return (
            local is not None
            and list(remote_ref.target_ids) == list(local.target_ids)
            and list(remote_ref.removed_ids) == list(local.removed_ids)
        )

    locals_ = {bm.name: bm for bm in repo.bookmarks()}
    by_name: dict[str, list] = {}
    for remote_ref in repo.remote_bookmarks():
        by_name.setdefault(remote_ref.name, []).append(remote_ref)

    items = []
    for name in sorted(set(locals_) | set(by_name)):
        local = locals_.get(name)
        refs = sorted(
            (r for r in by_name.get(name, []) if matches(r.remote)),
            key=lambda r: r.remote,
        )
        tracked = [r for r in refs if r.tracked]
        if not include_synced:
            tracked = [r for r in tracked if not synced(local, r)]
        if (include_local_only and local is not None and local.target_ids) or tracked:
            local_ids = list(local.target_ids) if local is not None else []
            items.append((local or _DeletedBookmark(name),
                          [(r, local_ids) for r in tracked]))
        if include_untracked:
            items.extend((r, ()) for r in refs if not r.tracked)
    return items


def bookmark(args) -> int:
    """`jj bookmark` dispatch — create/set/delete/forget/list/move/rename."""
    cmd = getattr(args, "bookmark_command", None)
    # list is read-only, no snapshot needed beyond _load
    if cmd == "list":
        try:
            _settings, ws, repo = _load(args)
            template = _resolve_template(_settings, ws, args, "bookmark_list")
            names = getattr(args, "names", None) or []
            with _formatter(_settings) as fmt:
                for ref, tracked in _list_items(repo, args):
                    if names and ref.name not in names:
                        continue
                    _print_ref(repo, _settings, ref, template, tracked,
                               fmt=fmt)
            return 0
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
    if cmd == "create":
        try:
            settings, ws, repo = _load(args)
            target = _resolve_one(repo, settings, args.revision)
            tx = _start_transaction(repo, settings)
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
            settings, ws, repo = _load(args)
            target = _resolve_one(repo, settings, args.revision)
            names = list(getattr(args, "names", None) or [])
            # Unlike `move`, this creates a bookmark that is not there
            # yet.
            tx = _start_transaction(repo, settings)
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
            settings, ws, repo = _load(args)
            tx = _start_transaction(repo, settings)
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
            tx = _start_transaction(repo, settings)
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
                print("No bookmarks to update.")
                return 0
            tx = _start_transaction(repo, settings)
            for bookmark in to_move:
                tx.set_bookmark(bookmark.name, target.id)
            _finish(tx, "point bookmark "
                        f"{', '.join(b.name for b in to_move)} to commit "
                        f"{target.id.hex()}", settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        return 0
    print(f"usage: pyjj bookmark {{create,set,delete,forget,list,move,rename}}", file=sys.stderr)
    return 2


def _name_matches(name: str, pattern: str) -> bool:
    """jj's string patterns, as far as a bookmark name needs them: a
    bare pattern is a glob, and the three prefixes name the rest."""
    for prefix, test in (
        ("exact:", lambda n, p: n == p),
        ("glob:", fnmatch.fnmatchcase),
        ("substring:", lambda n, p: p in n),
    ):
        if pattern.startswith(prefix):
            return test(name, pattern[len(prefix):].strip("\"'"))
    return fnmatch.fnmatchcase(name, pattern)
