"""templates subcommand: unset."""
import subprocess
import sys


def templates_unset(args) -> int:
    name = getattr(args, "name")
    is_repo = getattr(args, "repo", False)
    key = f"pyjj.templates.{name}"
    scope = "--repo" if is_repo else "--user"
    result = subprocess.run(["jj", "config", "unset", scope, key], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return result.returncode
    print(f"Unset {key}")
    return 0
