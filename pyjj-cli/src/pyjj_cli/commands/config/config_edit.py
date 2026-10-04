"""config subcommand: config_edit."""
import os
import shlex
import subprocess
import sys

import pyjj

from ..common import CommandError, apply_config_args
from .config_set import _scope, _workspace_root
from .paths import config_path, write_config


def _editor_cmd(settings):
    """Which editor to open, same precedence `describe` uses."""
    return (
        settings.get_string("ui.editor")
        or os.environ.get("JJ_EDITOR")
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or "nano"
    )


def config_edit(args) -> int:
    """`jj config edit --user|--repo|--workspace`: open the scoped file.

    Exactly one scope is required, the way jj's own parser requires it.
    The file is created empty first when missing: minting the secure
    directory without it is a state jj refuses outright (see `paths`),
    and real jj creates the file regardless of what the editor does.
    """
    scopes = [name for name, flag in (
        ("user", getattr(args, "user", False)),
        ("repo", getattr(args, "repo", False)),
        ("workspace", getattr(args, "workspace", False)),
        ("file", getattr(args, "file", None) is not None),
    ) if flag]
    if len(scopes) != 1:
        if not scopes:
            print("Error: config edit requires one of --user, --repo, "
                  "--workspace or --file", file=sys.stderr)
        else:
            first, second = scopes[0], scopes[1]
            print(f"Error: --{first} cannot be used with --{second}",
                  file=sys.stderr)
        return 2
    scope = scopes[0]
    try:
        settings = apply_config_args(pyjj.UserSettings())
        if scope == "file":
            from pathlib import Path
            path = Path(getattr(args, "file"))
            if path.parent and str(path.parent):
                path.parent.mkdir(parents=True, exist_ok=True)
        else:
            root = None
            if scope != "user":
                root = _workspace_root(args)
            path = config_path(root, scope, create=True)
    except (pyjj.JjError, CommandError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    if not path.exists():
        try:
            write_config(path, {})
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    proc = subprocess.run([*_editor_argv(settings), str(path)])
    return proc.returncode


def _editor_argv(settings) -> list:
    return shlex.split(_editor_cmd(settings))
