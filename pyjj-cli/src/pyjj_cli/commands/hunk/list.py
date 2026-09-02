"""hunk subcommand: hunk_list."""
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
    _wc_commit,
    complete_newline,
    _run_editor,
)

def hunk_list(args) -> int:
    """`pyjj hunk list [-r REV] [--format json|yaml|text]` — list hunks like jj-hunk."""
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision)
        # Collect file contents for the target's diff against parent
        file_contents = hunk_mod.collect_file_contents_for_commit(repo, target, settings)
        # Build output like jj-hunk: {files: [{path, status, hunks: [...]}, ...]}
        files_output = []
        for path, (before, after) in sorted(file_contents.items()):
            # Skip binary files for now
            try:
                before_s = before.decode()
                after_s = after.decode()
            except UnicodeDecodeError:
                files_output.append(
                    {"path": path, "status": "modified", "hunks": [], "binary": True}
                )
                continue
            hunks = hunk_mod.get_hunks_detailed(before_s, after_s)
            if not hunks and before != after:
                # For binary or whole-file case, still report
                hunks = []
            # Determine status
            if not before and after:
                status = "modified"
            elif not before:
                status = "added"
            elif not after:
                status = "removed"
            else:
                status = "modified"
            files_output.append({"path": path, "status": status, "hunks": hunks})
        output = {"files": files_output}
        fmt = args.format or "json"
        if fmt == "json":
            print(json.dumps(output, indent=2))
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore

                print(yaml.safe_dump(output, sort_keys=False))
            except ImportError:
                print("Error: PyYAML not installed, cannot output YAML", file=sys.stderr)
                return 1
        elif fmt == "text":
            # Simple text format like jj-hunk --files
            for f in files_output:
                print(f"{f['status'][0].upper()} {f['path']} ({len(f['hunks'])} hunks)")
                for h in f["hunks"]:
                    print(f"  hunk {h['index']} {h['type']} {h['id']}")
        else:
            print(f"Error: unknown format {fmt!r}", file=sys.stderr)
            return 1
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
