"""config subcommand: config_set."""
import sys
from pathlib import Path

import pyjj

from ..common import CommandError, _load
from .paths import config_path, read_config, set_key, write_config


def _target_path(args):
    """The file to act on: `--file` names it directly, otherwise the
    scope resolves to its file. A `--file` target is created with its
    parents, the way jj does; no recognized-location check is done."""
    target = getattr(args, "file", None)
    if target is not None:
        path = Path(target)
        if path.parent and str(path.parent):
            path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def config_set(args) -> int:
    """`jj config set --repo|--user|--workspace <name> <value>`."""
    scope = _scope(args)
    if scope is None and getattr(args, "file", None) is None:
        print("Error: No config target given; pass --user, --repo, "
              "--workspace or --file", file=sys.stderr)
        return 2
    try:
        path = _target_path(args)
        if path is None:
            root = _workspace_root(args) if scope != "user" else None
            # This one writes, so it may mint the scope's directory.
            path = config_path(root, scope, create=True)
        elif not path.exists():
            write_config(path, {})
        data = read_config(path)
        set_key(data, args.name, _parse(args.value))
        write_config(path, data)
    except (pyjj.JjError, CommandError, ValueError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    if args.name in ("user.name", "user.email"):
        # jj says this when the new value moves the author, because the
        # working-copy commit keeps the author it already has. Outside
        # a workspace there is no working copy, so jj says nothing.
        _warn_wc_author(args, _parse(args.value),
                        "name" if args.name == "user.name" else "email")
    return 0


def _warn_wc_author(args, value, part: str) -> None:
    """The full warning jj prints when the author setting changes."""
    try:
        _settings, ws, repo = _load(args)
        wc_hex = repo.view()[ws.workspace_name]
        author = repo.get_commit(pyjj.CommitId(wc_hex)).author
    except Exception:
        return
    current = author.name if part == "name" else author.email
    if isinstance(value, str) and value == current:
        return
    print("Warning: This setting will only impact future commits.\n"
          f"The author of the working copy will stay "
          f"\"{author.name} <{author.email}>\".\n"
          "To change the working copy author, use "
          "\"jj metaedit --update-author\".", file=sys.stderr)


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
