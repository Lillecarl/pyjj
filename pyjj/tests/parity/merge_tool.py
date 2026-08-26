#!/usr/bin/env python3
"""Deterministic stand-in for a 3-way merge tool, playing real jj's
resolve protocol: argv is [MODE, BASE, LEFT, RIGHT, OUTPUT, [PATH]] where
MODE is --marker ($output starts as the materialized conflict,
merge-tool-edits-conflict-markers = true) or --verbatim ($output starts
empty; whatever it holds afterwards is taken as fully resolved).

What gets written to $output is driven by PARITY_MERGE_SPEC (JSON):
  {"op": "pick_left"}            copy $left's bytes to $output
  {"op": "pick_right"}           copy $right's bytes to $output
  {"op": "content", "text": ..}  write these exact bytes
  {"op": "resolve_first_region",
   "text": ..}                   replace the FIRST conflict-marker region
                                 (<<<<<<< .. >>>>>>> lines inclusive) in
                                 the current $output content with `text`
  {"op": "unchanged"}            touch nothing (upstream EmptyOrUnchanged)
  {"op": "abort"}                exit 1 (upstream ToolAborted)

Launched without PARITY_MERGE_SPEC it exits 9 loudly, so a scenario can
never silently pass by forgetting to arm the tool.
"""
import json
import os
import shutil
import sys

MARKER_MIN = 7


def find_region_span(content: bytes) -> tuple[int, int] | None:
    """Byte span of the first conflict region: from the start of the first
    line beginning with a >=7-char '<<<<<<<' run to the end of the first
    later line beginning with a >=7-char '>>>>>>>'
    run."""
    start = None
    end = None
    pos = 0
    for line in content.splitlines(keepends=True):
        if start is None and line.startswith(b"<" * MARKER_MIN):
            stripped = line.lstrip(b"<")
            if not stripped or stripped[:1] in (b"\n", b"\r"):
                start = pos
        elif start is not None and line.startswith(b">" * MARKER_MIN):
            stripped = line.lstrip(b">")
            if not stripped or stripped[:1] in (b"\n", b"\r"):
                end = pos + len(line)
                break
        pos += len(line)
    return None if start is None else (start, end)


def main() -> int:
    spec_raw = os.environ.get("PARITY_MERGE_SPEC")
    if spec_raw is None:
        sys.stderr.write("parity-merge-tool: launched without PARITY_MERGE_SPEC\n")
        return 9
    spec = json.loads(spec_raw)

    mode = sys.argv[1]
    output_path = sys.argv[5]

    op = spec["op"]
    if op == "abort":
        return 1
    if op == "unchanged":
        return 0

    if op == "pick_left":
        shutil.copyfile(sys.argv[3], output_path)
    elif op == "pick_right":
        shutil.copyfile(sys.argv[4], output_path)
    elif op == "content":
        with open(output_path, "wb") as f:
            f.write(spec["text"].encode())
    elif op == "resolve_first_region":
        assert mode == "--marker", f"{op} needs marker mode"
        with open(output_path, "rb") as f:
            content = f.read()
        span = find_region_span(content)
        assert span is not None, "no conflict region found in $output"
        start, end = span
        replacement = spec["text"].encode().rstrip(b"\n")
        had_newline = content[end - 1 : end] == b"\n"
        tail = b"\n" if had_newline else b""
        new_content = content[:start] + replacement + tail + content[end:]
        with open(output_path, "wb") as f:
            f.write(new_content)
    else:
        sys.stderr.write(f"parity-merge-tool: unknown op {op!r}\n")
        return 9
    return 0


if __name__ == "__main__":
    sys.exit(main())
