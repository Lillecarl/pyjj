"""history subcommand: diff."""
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
    _print_diff_stats,
    _print_git_diff,
    _summary_lines,
    _ui_path_formatter,
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

def _diff_base(repo, settings, commit):
    """What a one-revision diff compares against: the first parent, or
    the root commit when there is none.

    jj diffs a parentless commit against the root commit, whose tree is
    empty, so every file in it reads as added. Every format goes through
    here, so none of them needs a branch for the case.
    """
    if commit.parent_ids:
        return repo.get_commit(commit.parent_ids[0])
    return repo.revset(settings, "root()")[0]


def _print_entries(args, ws, entries) -> None:
    """The path-only diff formats: `--name-only` and `--summary`.

    Both spell a path relative to the current directory, as jj does.
    `--summary` prefixes jj's one-letter status; `--name-only` prints
    the bare path.
    """
    to_ui_path = _ui_path_formatter(ws)
    if getattr(args, "name_only", False):
        for entry in entries:
            print(to_ui_path(entry.path))
        return
    for line in _summary_lines(entries, to_ui_path):
        print(line)


def diff(args) -> int:
    """`jj diff` — compare file contents between revisions."""
    try:
        settings, ws, repo = _load(args)
        paths = getattr(args, "filesets", None) or None
        # Determine from/to commits
        if getattr(args, "revisions", None) is not None:
            # -r mode: aggregate diff across revset (like jj diff -r B::D = from first parent to last)
            revs = repo.revset(settings, args.revisions)
            if not revs:
                return 0
            if len(revs) == 1:
                c = revs[0]
                if getattr(args, "git", False):
                    _print_git_diff(_diff_base(repo, settings, c), c, settings, paths)
                    return 0
                base = _diff_base(repo, settings, c)
                if getattr(args, "stat", False):
                    _print_diff_stats(base.diff_stats(c, settings, paths))
                    return 0
                _print_entries(args, ws, base.diff(c, paths))
                return 0
            # Multiple revs: diff from first's parent to last (simplified)
            first = revs[-1]
            last = revs[0]
            if getattr(args, "git", False):
                _print_git_diff(_diff_base(repo, settings, first), last, settings, paths)
                return 0
            base = _diff_base(repo, settings, first)
            if getattr(args, "stat", False):
                _print_diff_stats(base.diff_stats(last, settings, paths))
                return 0
            _print_entries(args, ws, base.diff(last, paths))
            return 0
        from_rev = getattr(args, "from_", None)
        to_rev = getattr(args, "to", None)
        if from_rev is not None or to_rev is not None:
            from_commit = _resolve_one(repo, settings, from_rev) if from_rev else _wc_commit(repo, ws)
            to_commit = _resolve_one(repo, settings, to_rev) if to_rev else _wc_commit(repo, ws)
            stat_base, stat_target = from_commit, to_commit
            if getattr(args, "git", False):
                _print_git_diff(from_commit, to_commit, settings, paths)
                return 0
            entries = from_commit.diff(to_commit, paths)
        else:
            # Default -r @
            wc = _wc_commit(repo, ws)
            if getattr(args, "git", False):
                _print_git_diff(_diff_base(repo, settings, wc), wc, settings, paths)
                return 0
            stat_base, stat_target = _diff_base(repo, settings, wc), wc
            entries = stat_base.diff(wc, paths)
        if getattr(args, "stat", False):
            _print_diff_stats(stat_base.diff_stats(stat_target, settings, paths))
            return 0
        _print_entries(args, ws, entries)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
