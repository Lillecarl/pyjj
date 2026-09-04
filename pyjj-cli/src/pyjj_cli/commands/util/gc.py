"""util subcommand: gc — backend garbage collection.

Mirrors `cli/src/commands/util/gc.rs`. The whole sweep lives in
`ReadonlyRepo.gc()`; this module only turns `--expire` into a cutoff.
"""
import sys

import pyjj

from ...commands.common import CommandError, _load

# jj's default: keep anything written in the last two weeks, reachable or
# not, because a concurrent process may not have referenced it yet.
_DEFAULT_MAX_AGE = 14 * 86400


def util_gc(args) -> int:
    expire = getattr(args, "expire", None)
    if expire is None:
        max_age = _DEFAULT_MAX_AGE
    elif expire == "now":
        max_age = 0
    else:
        print("Error: --expire only accepts 'now'", file=sys.stderr)
        return 1

    try:
        _settings, _ws, repo = _load(args)
        repo.gc(max_age)
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
    return 0
