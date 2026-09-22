"""config subcommand: config_unset."""
import sys

import pyjj

from ..common import CommandError
from .config_set import _scope, _workspace_root
from .paths import config_path, read_config, unset_key, write_config


def config_unset(args) -> int:
    """`jj config unset --repo|--user|--workspace <name>`."""
    scope = _scope(args)
    if scope is None:
        print("Error: No config target given; pass --user, --repo or --workspace",
              file=sys.stderr)
        return 2
    try:
        root = _workspace_root(args) if scope != "user" else None
        # Not `create=True`: a key that is not there fails below, and
        # minting the directory on the way out leaves one jj refuses
        # to read.
        path = config_path(root, scope)
        data = read_config(path)
        if not unset_key(data, args.name):
            print(f'Error: "{args.name}" doesn\'t exist', file=sys.stderr)
            return 1
        write_config(path, data)
    except (pyjj.JjError, CommandError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    return 0
