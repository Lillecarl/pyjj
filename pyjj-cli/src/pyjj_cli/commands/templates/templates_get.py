"""templates subcommand: get."""
import sys

from ..common import _pyjj_template, read_repo, command


@command
def templates_get(args) -> int:
    with read_repo(args) as (settings, ws, _):
        name = getattr(args, "name")
        value = _pyjj_template(settings, name, cwd=ws.workspace_root)
        if value is None:
            print(f"Error: template '{name}' not found", file=sys.stderr)
            return 1
        print(value)
        return 0
