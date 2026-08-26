#!/usr/bin/env python3
"""Scripted $EDITOR for parity scenarios.

Real `jj` shells out to an editor for several non-interactive-looking
flows (bare `describe`/`commit`, squash message combining, split's first
half). This script plays that role deterministically: it applies one
transform, taken from the PARITY_EDITOR_SPEC environment variable (JSON),
to the file named in argv[1]:

    {"op": "set", "value": "..."}          replace the whole buffer
    {"op": "append", "value": "..."}       append after existing content
    {"op": "drop_jj_comments"}             delete lines starting with "JJ:"

Invoked without a spec it fails loudly -- an unexpected editor launch in
a scenario is a bug, not something to silently accept.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    path = sys.argv[1]
    raw = os.environ.get("PARITY_EDITOR_SPEC")
    if not raw:
        print("PARITY_EDITOR_SPEC not set; unexpected editor launch", file=sys.stderr)
        return 77
    spec = json.loads(raw)

    with open(path, encoding="utf-8") as f:
        text = f.read()

    op = spec["op"]
    if op == "set":
        text = spec["value"]
    elif op == "append":
        text += spec["value"]
    elif op == "drop_jj_comments":
        text = "".join(
            line + "\n" for line in text.splitlines()
            if not line.startswith("JJ:")
        )
    else:
        print(f"unknown editor op: {op}", file=sys.stderr)
        return 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
