"""util subcommand: exec — run an external command via jj.

Mirrors `cli/src/commands/util/exec.rs`. Two details matter for parity.
It does not snapshot the working copy: jj reaches for the workspace
*loader*, not the command helper, so running this leaves the repository
exactly as it was. And it exits with the child's own status.
"""
import os
import subprocess
import sys

import pyjj


def util_exec(args) -> int:
    if not getattr(args, "command_name", None):
        print("Error: Command argument is required", file=sys.stderr)
        return 2

    env = os.environ.copy()
    try:
        settings = pyjj.UserSettings()
        ws = pyjj.Workspace.load(settings, args.repository)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError):
        # jj only sets the variable when a workspace is found, and runs
        # the command either way.
        pass
    else:
        env["JJ_WORKSPACE_ROOT"] = str(ws.workspace_root)

    # `argparse.REMAINDER` keeps a leading `--` separator; jj's clap does
    # not.
    extra = list(getattr(args, "command_args", None) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]

    try:
        return subprocess.run([args.command_name, *extra], env=env).returncode
    except OSError as e:
        print(f"Error: Failed to execute external command "
              f"'{args.command_name}': {e}", file=sys.stderr)
        return 1
