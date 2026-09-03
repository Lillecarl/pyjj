"""templates subcommand: list."""
import subprocess
import sys

import pyjj
from ..common import _load


def templates_list(args) -> int:
    try:
        settings, _, _ = _load(args)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    # Use jj config list to enumerate, filter pyjj.templates.*
    try:
        cmd = ["jj", "config", "list", "pyjj.templates"]
        if getattr(args, "repo", False):
            cmd.insert(2, "--repo")
            # jj config list doesn't have --repo filter; we do post-filter
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout, end="")
            return 0
    except Exception:
        pass

    # Fallback: iterate via settings.get_string for known? Instead list via stacked config layers.
    # We don't have direct enumeration API, so try to list via jj config list --user/--repo and grep.
    # For now, try both user and repo
    for scope in (["--user"], ["--repo"]):
        try:
            result = subprocess.run(["jj", "config", "list"] + scope + ["pyjj.templates"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                print(result.stdout, end="")
        except Exception:
            continue
    # If still empty, try generic list and filter
    try:
        result = subprocess.run(["jj", "config", "list"], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "pyjj.templates" in line:
                    print(line)
            return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
