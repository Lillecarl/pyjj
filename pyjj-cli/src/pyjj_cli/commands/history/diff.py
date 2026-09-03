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

def diff(args) -> int:
    """`jj diff` — compare file contents between revisions."""
    try:
        settings, _ws, repo = _load(args)
        paths = getattr(args, "filesets", None) or None
        # Determine from/to commits
        if getattr(args, "revisions", None) is not None:
            # -r mode: aggregate diff across revset (like jj diff -r B::D = from first parent to last)
            revs = repo.revset(settings, args.revisions)
            if not revs:
                return 0
            if len(revs) == 1:
                c = revs[0]
                if c.parent_ids:
                    parent = repo.get_commit(c.parent_ids[0])
                    entries = parent.diff(c, paths)
                    name_only = getattr(args, "name_only", False)
                    summary = getattr(args, "summary", False)
                    for e in entries:
                        if name_only:
                            print(e.path)
                        elif summary:
                            print(f"{e.status:8} {e.path}")
                        else:
                            print(f"{e.status:8} {e.path}")
                else:
                    # Root: list files as added
                    for p in c.list_files(paths):
                        if getattr(args, "name_only", False):
                            print(p)
                        else:
                            print(f"added    {p}")
                return 0
            # Multiple revs: diff from first's parent to last (simplified)
            first = revs[-1]
            last = revs[0]
            if first.parent_ids:
                base = repo.get_commit(first.parent_ids[0])
                entries = base.diff(last, paths)
                for e in entries:
                    print(f"{e.status:8} {e.path}")
            else:
                for p in last.list_files(paths):
                    print(f"added    {p}")
            return 0
        from_rev = getattr(args, "from_", None)
        to_rev = getattr(args, "to", None)
        if from_rev is not None or to_rev is not None:
            from_commit = _resolve_one(repo, settings, from_rev) if from_rev else _wc_commit(repo, _ws)
            to_commit = _resolve_one(repo, settings, to_rev) if to_rev else _wc_commit(repo, _ws)
            entries = from_commit.diff(to_commit, paths)
        else:
            # Default -r @
            wc = _wc_commit(repo, _ws)
            if wc.parent_ids:
                parent = repo.get_commit(wc.parent_ids[0])
                entries = parent.diff(wc, paths)
            else:
                for p in wc.list_files(paths):
                    if getattr(args, "name_only", False):
                        print(p)
                    else:
                        print(f"added    {p}")
                return 0
        name_only = getattr(args, "name_only", False)
        for e in entries:
            if name_only:
                print(e.path)
            else:
                print(f"{e.status:8} {e.path}")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
