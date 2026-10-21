"""hunk subcommand: hunk_schema."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pyjj.hunk as hunk_mod
import yaml

if TYPE_CHECKING:
    import argparse


def hunk_schema(args: argparse.Namespace) -> int:
    """`pyjj hunk schema` — dump JSON schema for LLM tool-calling."""
    schema = hunk_mod.Spec.model_json_schema()
    if getattr(args, "format", "json") == "yaml":
        print(yaml.safe_dump(schema, sort_keys=False))
    else:
        print(json.dumps(schema, indent=2))
    return 0
