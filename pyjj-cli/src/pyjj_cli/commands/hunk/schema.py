"""hunk subcommand: hunk_schema."""
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

def hunk_schema(args) -> int:
    """`pyjj hunk schema` — dump JSON schema for LLM tool-calling."""
    try:
        fmt = getattr(args, "format", "json")
        if not hunk_mod.HAS_PYDANTIC:
            print("Error: pydantic not available, cannot generate schema", file=sys.stderr)
            return 1
        schema = hunk_mod.SpecModel.model_json_schema()  # type: ignore
        if fmt == "json":
            print(json.dumps(schema, indent=2))
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore

                print(yaml.safe_dump(schema, sort_keys=False))
            except ImportError:
                print("Error: PyYAML not installed, cannot output YAML", file=sys.stderr)
                return 1
        else:
            print(f"Error: unknown format {fmt!r}", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
