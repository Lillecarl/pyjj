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
    """`jj show` — show revision metadata and diff."""
    try:
        settings, ws, repo = _load(args)
        revs = args.revisions or ["@"]
        commits = _resolve_all(repo, settings, revs)
        for commit in commits:
            desc = commit.description or "(no description set)"
            print(f"Commit: {commit.id.hex()}")
            print(f"Change: {commit.change_id.hex()}")
            print(f"Author: {commit.author.name} <{commit.author.email}>")
            print(f"Description:\n  {desc.strip()}")
            if getattr(args, "no_patch", False):
                continue
            if commit.parent_ids:
                parent = repo.get_commit(commit.parent_ids[0])
                if getattr(args, "stat", False):
                    _print_diff_stats(parent.diff_stats(commit, settings))
                    continue
                entries = parent.diff(commit)
            else:
                entries = []
                for p in commit.list_files():
                    print(f"added    {p}")
                continue
            for e in entries:
                if getattr(args, "name_only", False):
                    print(e.path)
                else:
                    print(f"{e.status:8} {e.path}")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
