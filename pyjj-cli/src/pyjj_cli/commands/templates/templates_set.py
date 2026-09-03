"""templates subcommand: set."""
import subprocess
import sys

import pyjj
from ..common import _load

# Allowed template variables — for validation
_ALLOWED_VARS = {
    "change_id", "commit_id", "change_id_short", "commit_id_short",
    "change_id_short_raw", "commit_id_short_raw",
    "author", "author_name", "author_email", "author_display",
    "description", "description_display",
    "bookmarks", "bookmarks_str", "bookmarks_display",
    "datetime", "datetime_display",
    "is_wc", "is_current_wc", "is_root",
    "commit",
}


def _validate_template(value: str) -> tuple[bool, str]:
    try:
        from jinja2 import Environment, StrictUndefined, meta

        env = Environment(undefined=StrictUndefined)
        ast = env.parse(value)
        vars_found = meta.find_undeclared_variables(ast)
        unknown = vars_found - _ALLOWED_VARS
        if unknown:
            return False, f"unknown variables: {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(_ALLOWED_VARS))})"
        # Try compile
        env.from_string(value)
        return True, ""
    except Exception as e:
        return False, str(e)


def templates_set(args) -> int:
    name = getattr(args, "name")
    value = getattr(args, "value")
    is_repo = getattr(args, "repo", False)

    ok, msg = _validate_template(value)
    if not ok:
        print(f"Error: template validation failed: {msg}", file=sys.stderr)
        return 1

    key = f"pyjj.templates.{name}"
    scope = "--repo" if is_repo else "--user"
    # jj config set expects TOML string, so we need to quote as TOML string
    # Use triple single quotes to avoid shell quoting issues: '''...'''
    toml_value = "'''" + value.replace("'''", "\\'\\'\\'") + "'''"
    result = subprocess.run(["jj", "config", "set", scope, key, toml_value], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return result.returncode
    print(f"Set {key} = {value}")
    return 0
