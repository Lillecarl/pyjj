"""operation subcommand: next_commit."""
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
    _commit_summary,
    _finish,
    _load,
    _nearest_conflicted,
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
    _move_to,
    _walk,
    _wants_edit,
)

def next_commit(args) -> int:
    """`jj next [OFFSET]`: move the working copy forward.

    Without `--edit` the new working copy is a *child* of the commit
    `offset` steps ahead of `@`'s parent, and `@` itself is excluded from
    that walk -- so from a sibling branch `next` lands on the other line
    of development, not back on itself. With `--edit` the working copy
    becomes the descendant `offset` steps ahead of `@`.

    `--conflict` takes no offset (jj refuses the two together) and
    jumps to the nearest conflicted descendant instead, with the same
    edit/no-edit shape around it.
    """
    try:
        settings, ws, repo = _load(args)
        edit = _wants_edit(args)
        wc = _wc_commit(repo, ws)

        if getattr(args, "conflict", False):
            if getattr(args, "amount", None) is not None:
                print("Error: --conflict cannot be used with [OFFSET]",
                      file=sys.stderr)
                return 2
            if edit:
                targets = _nearest_conflicted(
                    repo, settings, [wc.id.hex()], "children")
                if not targets:
                    print("Error: The working copy has no descendants "
                          "with conflicts", file=sys.stderr)
                    print(f"Hint: Working copy: "
                          f"{_commit_summary(repo, settings, wc)}",
                          file=sys.stderr)
                    return 1
            else:
                if repo.revset(settings, f"children({wc.id.hex()})"):
                    print("Error: The working copy must not have any children",
                          file=sys.stderr)
                    print("Hint: Create a new commit on top of this one "
                          "or use `--edit`", file=sys.stderr)
                    return 1
                starts = [i.hex() for i in wc.parent_ids]
                targets = _nearest_conflicted(
                    repo, settings, starts, "children",
                    exclude={wc.id.hex()})
                if not targets:
                    print("Error: The working copy parent(s) have no other "
                          "descendants with conflicts", file=sys.stderr)
                    for pid in wc.parent_ids:
                        parent = repo.get_commit(pid)
                        print(f"Hint: Working copy parent: "
                              f"{_commit_summary(repo, settings, parent)}",
                              file=sys.stderr)
                    return 1
            return _move_to(args, settings, ws, repo, targets, edit, "next")

        offset = getattr(args, "amount", 1) or 1

        if edit:
            targets = _walk(repo, settings, [wc.id.hex()], "children", offset)
            if not targets:
                print(f"Error: No descendant found {offset} commit(s) forward "
                      "from the working copy", file=sys.stderr)
                return 1
        else:
            if repo.revset(settings, f"children({wc.id.hex()})"):
                print("Error: The working copy must not have any children",
                      file=sys.stderr)
                return 1
            starts = [i.hex() for i in wc.parent_ids]
            targets = _walk(repo, settings, starts, "children", offset,
                            exclude={wc.id.hex()})
            if not targets:
                print(f"Error: No other descendant found {offset} commit(s) "
                      "forward from the working copy parent(s)", file=sys.stderr)
                return 1

        return _move_to(args, settings, ws, repo, targets, edit, "next")
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
