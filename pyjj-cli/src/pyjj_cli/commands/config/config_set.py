"""config subcommand: config_set."""
import sys

import pyjj

from ..common import CommandError, _load
from .paths import config_path, read_config, set_key, write_config


def config_set(args) -> int:
    """`jj config set --repo|--user|--workspace <name> <value>`."""
    scope = _scope(args)
    if scope is None:
        print("Error: No config target given; pass --user, --repo or --workspace",
              file=sys.stderr)
        return 2
    try:
        root = _workspace_root(args) if scope != "user" else None
        path = config_path(root, scope)
        data = read_config(path)
        set_key(data, args.name, _parse(args.value))
        write_config(path, data)
    except (pyjj.JjError, CommandError, ValueError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    if args.name in ("user.name", "user.email"):
        # jj says this, because the working-copy commit keeps the author
        # it already has.
        print("Warning: This setting will only impact future commits.",
              file=sys.stderr)
    return 0


def _scope(args):
    if getattr(args, "workspace", False):
        return "workspace"
    if getattr(args, "repo", False):
        return "repo"
    if getattr(args, "user", False):
        return "user"
    return None


def _workspace_root(args):
    _settings, ws, _repo = _load(args)
    return ws.workspace_root


def _parse(text: str):
    """jj accepts a TOML value; a bare word is a string."""
    lowered = text.strip()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(lowered)
    except ValueError:
        pass
    if len(lowered) >= 2 and lowered[0] == lowered[-1] and lowered[0] in "\"'":
        return lowered[1:-1]
    return text
