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
"""

from __future__ import annotations

import json
import os
import shutil
import sys


def main() -> int:
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
