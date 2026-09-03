"""templates subcommand: list."""
import subprocess
import sys


def templates_list(args) -> int:
    # `jj config list` walks every layer, repo config included, so it needs
    # no help from UserSettings (which does not load repo config -- see
    # AGENTS.md's Config section).
    cmd = ["jj", "config", "list"]
    if getattr(args, "repo", False):
        cmd.append("--repo")
    cmd.append("pyjj.templates")
    cwd = getattr(args, "repository", None) or "."
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    print(result.stdout, end="")
    return 0
