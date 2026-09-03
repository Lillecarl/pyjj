"""config subcommand: config_list."""
import sys

import pyjj

from ..common import CommandError
from .config_set import _scope, _workspace_root
from .paths import config_path, read_config


def config_list(args) -> int:
    """`jj config list [NAME]`: list what the config files set.

    With a scope flag this reads that one file. Without one it reads the
    user file plus this repository's, which is what a caller asking
    "what is set here" means -- pyjj has no way to enumerate the built-in
    defaults the way jj's own layered config does, so those are absent.
    """
    prefix = getattr(args, "name", None)
    try:
        entries = _entries(args)
    except (pyjj.JjError, CommandError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    shown = 0
    for name, value in sorted(entries.items()):
        if prefix and not (name == prefix or name.startswith(prefix + ".")):
            continue
        print(f"{name} = {_render(value)}")
        shown += 1
    if not shown:
        print("Warning: No matching config variables found", file=sys.stderr)
    return 0


def _entries(args) -> dict:
    scope = _scope(args)
    if scope is not None:
        root = _workspace_root(args) if scope != "user" else None
        return _flatten(read_config(config_path(root, scope)))
    entries = _flatten(read_config(config_path(None, "user")))
    try:
        root = _workspace_root(args)
    except (pyjj.JjError, CommandError):
        return entries
    for scope in ("repo", "workspace"):
        entries.update(_flatten(read_config(config_path(root, scope))))
    return entries


def _flatten(data: dict, prefix: str = "") -> dict:
    flat = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def _render(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_render(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
