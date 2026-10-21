"""hunk subcommand: hunk_schema."""
import json

import yaml

import pyjj.hunk as hunk_mod


def hunk_schema(args) -> int:
    """`pyjj hunk schema` — dump JSON schema for LLM tool-calling."""
    schema = hunk_mod.Spec.model_json_schema()
    if getattr(args, "format", "json") == "yaml":
        print(yaml.safe_dump(schema, sort_keys=False))
    else:
        print(json.dumps(schema, indent=2))
    return 0
