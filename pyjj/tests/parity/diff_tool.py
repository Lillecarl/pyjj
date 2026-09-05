#!/usr/bin/env python3
"""Scripted merge-tools diff editor for parity scenarios.

Real `jj` materializes the changed paths into $left/$right directories
and invokes the configured tool; after it exits, whatever exists under
$right becomes the selected state. This script plays that role
deterministically. Spec from PARITY_DIFF_SPEC (JSON):

    {"op": "keep", "paths": [...]}     delete everything else under $right
    {"op": "drop", "paths": [...]}     delete these paths under $right
    {"op": "edit", "edits": [{"path": ..., "find": ..., "replace": ...}]}

argv: <script> --edit $left $right   (left is ignored: read-only side)

`--format` is the other protocol the same program serves. `jj diff
--tool` runs a tool to *print* a diff rather than to edit one: jj
writes the two sides into the same pair of directories, runs the tool
with its working directory set to the pair, and copies its output
through unchanged. This script's format mode walks both sides and
prints one line a path, which is deterministic across two repositories
because it names nothing outside them.

argv: <script> --format $left $right
"""

from __future__ import annotations

import json
import os
import shutil
import sys


def _walk(root: str) -> dict[str, bytes]:
    """Every file under `root`, keyed by its path relative to it."""
    found = {}
    for directory, _subdirs, names in os.walk(root):
        for name in names:
            full = os.path.join(directory, name)
            found[os.path.relpath(full, root)] = open(full, "rb").read()
    return found


def format_diff(left: str, right: str) -> int:
    """Print what changed between the two directories, one line a path.

    The paths are relative and the contents come from the repository,
    so two repositories holding the same commits print the same thing.
    """
    before, after = _walk(left), _walk(right)
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old is None:
            print(f"added {path}: {new.decode('utf-8', 'replace').strip()}")
        elif new is None:
            print(f"removed {path}: {old.decode('utf-8', 'replace').strip()}")
        elif old != new:
            print(f"changed {path}: "
                  f"{old.decode('utf-8', 'replace').strip()} -> "
                  f"{new.decode('utf-8', 'replace').strip()}")
    return 0


def main() -> int:
    if sys.argv[1] == "--format":
        return format_diff(sys.argv[2], sys.argv[3])
    # edit-args template is ["--edit", "$left", "$right"]
    right = sys.argv[-1]
    raw = os.environ.get("PARITY_DIFF_SPEC")
    if not raw:
        print("PARITY_DIFF_SPEC not set; unexpected diff-editor launch",
              file=sys.stderr)
        return 77
    spec = json.loads(raw)

    def apply(op: dict) -> None:
        kind = op["op"]
        if kind == "keep":
            keep = set(op["paths"])
            for p in sorted(os.listdir(right)):
                full = os.path.join(right, p)
                if os.path.isfile(full) and p not in keep:
                    os.unlink(full)
        elif kind == "drop":
            for name in op["paths"]:
                full = os.path.join(right, name)
                if os.path.exists(full):
                    os.unlink(full)
        elif kind == "edit":
            for e in op["edits"]:
                full = os.path.join(right, e["path"])
                with open(full, encoding="utf-8") as f:
                    text = f.read()
                assert e["find"] in text, f"{e['find']!r} not in {full}"
                text = text.replace(e["find"], e["replace"])
                with open(full, "w", encoding="utf-8") as f:
                    f.write(text)
        else:
            print(f"unknown diff op: {kind}", file=sys.stderr)
            raise SystemExit(1)

    ops = spec.get("sequence") or [spec]
    for op in ops:
        apply(op)
    return 0


if __name__ == "__main__":
    sys.exit(main())
