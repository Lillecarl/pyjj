"""pyjj-cli commands: operation."""
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

def evolog(args) -> int:
    try:
        settings, _ws, repo = _load(args)
        rev = getattr(args, "revisions", "@")
        commits = repo.revset(settings, rev)
        if not commits:
            print("No revisions to show")
            return 0
        # For now, just show the log for the revision's change id's evolution
        # Use the commit's change id to find all commits with same change id via revset?
        # Simplified: just show the single commit
        for c in commits:
            desc = c.description.splitlines()[0] if c.description else "(no description)"
            print(f"{c.change_id.hex()[:12]} {c.id.hex()[:12]} {desc}")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def next_commit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        amount = getattr(args, "amount", 1) or 1
        # Find child of @
        wc = _wc_commit(repo, ws)
        # Find children of wc via revset children(@)
        children = repo.revset(settings, f"children({wc.id.hex()})")
        if not children:
            print("No child revision", file=sys.stderr)
            return 1
        # For amount >1, walk
        target = children[0]
        for _ in range(1, amount):
            nxt = repo.revset(settings, f"children({target.id.hex()})")
            if not nxt:
                break
            target = nxt[0]
        tx = repo.start_transaction(settings)
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"next to {target.id.hex()[:8]}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def prev_commit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        amount = getattr(args, "amount", 1) or 1
        wc = _wc_commit(repo, ws)
        if not wc.parent_ids:
            print("No parent revision", file=sys.stderr)
            return 1
        target = repo.get_commit(wc.parent_ids[0])
        for _ in range(1, amount):
            if not target.parent_ids:
                break
            target = repo.get_commit(target.parent_ids[0])
        tx = repo.start_transaction(settings)
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"prev to {target.id.hex()[:8]}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def parallelize(args) -> int:
    print("Error: parallelize is not yet supported", file=sys.stderr)
    return 2

def interdiff(args) -> int:
    print("Error: interdiff is not yet supported", file=sys.stderr)
    return 2

def op_log(args) -> int:
    try:
        _settings, _ws, repo = _load(args)
        for op in repo.operation_log():
            print(f"{op.id.hex()[:12]} {op.description}")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def op_show(args) -> int:
    try:
        _settings, _ws, repo = _load(args)
        op_id = getattr(args, "operation", None)
        if op_id:
            op = repo.load_operation(op_id)
        else:
            op = repo.operation
        print(f"Operation: {op.id.hex()}")
        print(f"Description: {op.description}")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def op_abandon(args) -> int:
    try:
        _settings, ws, _repo = _load(args)
        ops = getattr(args, "operations", [])
        # Join with .. for range syntax if multiple
        if len(ops) == 1:
            op_str = ops[0]
        else:
            op_str = "..".join(ops)
        ws.op_abandon(op_str)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

def op_diff(args) -> int:
    print("Error: op diff is not yet supported", file=sys.stderr)
    return 2

def op_integrate(args) -> int:
    print("Error: op integrate is not yet supported", file=sys.stderr)
    return 2

def op_revert(args) -> int:
    print("Error: op revert is not yet supported", file=sys.stderr)
    return 2

def undo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _undone, _restored_to, description = tx.undo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def redo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _redone, _restored_to, description = tx.redo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def op_restore(args) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    try:
        settings, ws, repo = _load(args)
        target = repo.load_operation(args.operation_pos)
        tx = repo.start_transaction(settings)
        tx.restore_operation(target)
        _restore_view_command(
            tx, f"restore operation {args.operation_pos}", settings, ws, repo
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

