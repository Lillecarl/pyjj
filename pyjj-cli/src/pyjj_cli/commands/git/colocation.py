"""git subcommand: git_colocation."""
import sys

import pyjj
from ..common import (
    command,
    read_repo,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def git_colocation(args) -> int:
    """`jj git colocation` — manage colocation status."""
    with read_repo(args) as (_settings, ws, _repo):
        sub = getattr(args, "colocation_command", None)
        # The faithful detector, not the mere presence of a `.git`
        # entry (an unrelated repo's file there would lie) -- the
        # binding opens the workdir repo the way jj itself does.
        is_colocated = ws.is_colocated()
        if sub == "status":
            if is_colocated:
                print(f"Workspace '{ws.workspace_name}' is currently "
                      f"colocated with Git.")
            else:
                print(f"Workspace '{ws.workspace_name}' is currently not "
                      f"colocated with Git.")
            head = ws.git_head_hex()
            print(f"Last imported/exported Git HEAD: "
                  f"{head if head is not None else '(none)'}")
            if is_colocated:
                print("Hint: To disable colocation, run: "
                      "`jj git colocation disable`", file=sys.stderr)
            else:
                print("Hint: To enable colocation, run: "
                      "`jj git colocation enable`", file=sys.stderr)
            return 0
        elif sub == "enable":
            if is_colocated:
                print("Workspace is already colocated with Git.")
                return 0
            # Enabling colocation would require moving the git dir from .jj/repo/store/git to .git
            # This is not yet implemented in pyjj — we just report and return error
            print("Error: converting to colocated repo is not yet supported", file=sys.stderr)
            return 1
        elif sub == "disable":
            if not is_colocated:
                print("Workspace is already not colocated with Git.")
                return 0
            print("Error: converting to non-colocated repo is not yet supported", file=sys.stderr)
            return 1
        else:
            print("usage: pyjj git colocation {status,enable,disable}", file=sys.stderr)
            return 2
