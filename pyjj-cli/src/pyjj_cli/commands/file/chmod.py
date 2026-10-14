"""file subcommand: file_chmod."""

from ..common import (
    _start_transaction,
    _check_rewritable,
    _finish,
    _load,
    _resolve_one,
    command,
)

@command
def file_chmod(args) -> int:
    settings, ws, repo = _load(args)
    rev = getattr(args, "revision", "@")
    commit = _resolve_one(repo, settings, rev)
    mode = getattr(args, "mode", "x")
    executable = mode in ("x", "executable")
    tx = _start_transaction(repo, settings)
    _check_rewritable(tx, settings, [commit])
    for path in getattr(args, "paths", []):
        b = tx.set_executable(commit, path, executable)
        b.write(repo)
    _finish(tx, f"chmod {rev}", settings, ws, repo)
    return 0
