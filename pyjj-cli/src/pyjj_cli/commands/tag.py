"""pyjj-cli commands: tag."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from .common import (
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

def tag_list(args) -> int:
    try:
        _settings, _ws, repo = _load(args)
        names = getattr(args, "names", None) or []
        tags = repo.tags()  # list[Tag]
        if names:
            tags = [t for t in tags if t.name in names]
        for tag in sorted(tags, key=lambda t: t.name):
            if tag.has_conflict:
                ids = " ".join(t.hex()[:12] for t in tag.target_ids)
                print(f"{tag.name}@conflicted: {ids}")
            elif tag.target_ids:
                print(f"{tag.name}: {tag.target_ids[0].hex()[:12]}")
            else:
                print(f"{tag.name}: (deleted)")
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def tag_set(args) -> int:
    try:
        settings, ws, repo = _load(args)
        rev = getattr(args, "revision", "@")
        target = _resolve_one(repo, settings, rev)
        tx = repo.start_transaction(settings)
        for name in getattr(args, "names", []):
            tx.set_tag(name, target.id)
        _finish(tx, f"set tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def tag_delete(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        for name in getattr(args, "names", []):
            if repo.get_tag(name) is None:
                print(f"Warning: No such tag: {name}", file=sys.stderr)
                continue
            tx.delete_tag(name)
        _finish(tx, f"delete tag {','.join(getattr(args, 'names', []))}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def tag_track(args) -> int:
    print("Error: tag track is not yet supported", file=sys.stderr)
    return 2

def tag_untrack(args) -> int:
    print("Error: tag untrack is not yet supported", file=sys.stderr)
    return 2

