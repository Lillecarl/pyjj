"""file subcommand: file_chmod."""

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_one,
    command,
    write_tx,
)

@command
def file_chmod(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        rev = getattr(args, "revision", "@")
        commit = _resolve_one(repo, settings, rev)
        mode = getattr(args, "mode", "x")
        executable = mode in ("x", "executable")
        _check_rewritable(tx, settings, [commit])
        for path in getattr(args, "paths", []):
            b = tx.set_executable(commit, path, executable)
            b.write(repo)
        _finish(tx, f"chmod {rev}", settings, ws, repo)
        return 0
