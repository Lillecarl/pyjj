"""hunk subcommand: hunk_list."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import pyjj.hunk as hunk_mod
import yaml

from ..common import (
    _resolve_one,
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse


def _status(before: bytes | None, after: bytes | None) -> str:
    if before is None:
        return "added"
    if after is None:
        return "removed"
    return "modified"


@command(catch=(ValueError,))
def hunk_list(args: argparse.Namespace) -> int:
    """`pyjj hunk list [-r REV] [--format json|yaml|text]` — list hunks like jj-hunk."""
    with read_repo(args) as (settings, ws, repo):
        target = _resolve_one(repo, settings, args.revision)
        files_output: list[dict[str, Any]] = []
        contents = hunk_mod.collect_file_contents_for_commit(repo, target)
        for path, (before, after) in sorted(contents.items()):
            entry: dict[str, Any] = {"path": path, "status": _status(before, after)}
            old, new = before or b"", after or b""
            if hunk_mod.is_binary(old) or hunk_mod.is_binary(new):
                files_output.append({**entry, "hunks": [], "binary": True})
                continue
            entry["hunks"] = [h.to_json() for h in hunk_mod.get_hunks(old, new)]
            files_output.append(entry)
        output = {"files": files_output}
        if args.format == "yaml":
            print(yaml.safe_dump(output, sort_keys=False))
        elif args.format == "text":
            for f in files_output:
                print(f"{f['status'][0].upper()} {f['path']} ({len(f['hunks'])} hunks)")
                for h in f["hunks"]:
                    print(f"  hunk {h['index']} {h['type']} {h['id']}")
        else:
            print(json.dumps(output, indent=2))
        return 0
