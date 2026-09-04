"""history subcommand: show."""
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
    _bookmarks_by_commit,
    _detailed_signature,
    _diff_base,
    _indent,
    _print_diff,
    _tags_by_commit,
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
    _print_diff_stats,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

def show(args) -> int:
    """`jj show` — a commit's metadata and its diff."""
    try:
        settings, ws, repo = _load(args)
        revs = args.revisions or ["@"]
        commits = _resolve_all(repo, settings, revs)
        bookmarks = _bookmarks_by_commit(repo, remotes=True)
        tags = _tags_by_commit(repo)
        for commit in commits:
            print(f"Commit ID: {commit.id.hex()}")
            print(f"Change ID: {commit.change_id.reverse_hex()}")
            names = bookmarks.get(commit.id.hex(), [])
            if names:
                print(f"Bookmarks: {' '.join(names)}")
            commit_tags = tags.get(commit.id.hex(), [])
            if commit_tags:
                print(f"Tags     : {' '.join(commit_tags)}")
            print(f"Author   : {_detailed_signature(commit.author)}")
            print(f"Committer: {_detailed_signature(commit.committer)}")
            print()
            description = commit.description.rstrip() or "(no description set)"
            print(_indent(description))
            print()
            if getattr(args, "no_patch", False):
                continue
            base = _diff_base(repo, settings, commit)
            _print_diff(args, ws, settings, base, commit, None)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
