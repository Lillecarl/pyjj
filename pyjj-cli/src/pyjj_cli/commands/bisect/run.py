"""bisect subcommand: run — binary-search for the first bad revision.

Mirrors `cli/src/commands/bisect/run.rs`. The search itself is
`pyjj.Bisector`; this module only drives it, and the order of repo
operations matters: each candidate is checked out in its own
transaction described `Updated to revision <hex> for bisection`, the
same shape `jj` writes, so the operation log comes out the same.
"""
import os
import subprocess
import sys

import pyjj

from ..common import CommandError, _finish, _load

# The exit-status protocol `jj bisect run` documents.
_SKIP_STATUS = 125
_ABORT_STATUS = 127


def _evaluation_for(status: int) -> str:
    if status == 0:
        return "good"
    if status == _SKIP_STATUS:
        return "skip"
    if status == _ABORT_STATUS:
        return "abort"
    return "bad"


def _summary(commit) -> str:
    """A one-line commit summary, in the shape `pyjj log` uses."""
    description = commit.description.splitlines()[0] if commit.description else "(no description set)"
    return f"{commit.change_id.hex()[:8]} {commit.id.hex()[:8]} {description}"


def bisect_run(args) -> int:
    if not getattr(args, "cmd", None):
        print("Error: Command argument is required", file=sys.stderr)
        return 2

    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    # The op to roll back to. Captured before the search creates anything.
    initial_op = repo.operation_id

    try:
        bisector = pyjj.Bisector(repo, settings, list(args.range))
    except (pyjj.JjError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    # `argparse.REMAINDER` keeps a leading `--` separator; jj's clap does not.
    extra = list(getattr(args, "cmd_args", None) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    argv = [args.cmd] + extra

    while True:
        try:
            step = bisector.next_step()
        except (pyjj.JjError, ValueError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1

        if step.kind == "done":
            break

        commit = step.commit
        lower, upper = bisector.remaining_count()
        steps = 0
        while (1 << steps) < lower + 1:
            steps += 1
        if upper == lower:
            print(f"Bisecting: {lower} revisions left to test after this "
                  f"(roughly {steps} steps)")
        else:
            print(f"Bisecting: at least {lower} revisions left to test after this "
                  f"(at least roughly {steps} steps)")
        print(f"Now evaluating: {_summary(commit)}")

        commit_id_hex = commit.id.hex()
        try:
            tx = repo.start_transaction(settings)
            tx.check_out(ws.workspace_name, commit)
            _finish(tx, f"Updated to revision {commit_id_hex} for bisection",
                    settings, ws, repo)
        except (pyjj.JjError, CommandError) as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1

        env = os.environ.copy()
        env["JJ_BISECT_TARGET"] = commit_id_hex
        try:
            status = subprocess.run(argv, cwd=ws.workspace_root, env=env).returncode
        except OSError as e:
            print(f"Error: Failed to run evaluation command: {e}", file=sys.stderr)
            return 1

        evaluation = _evaluation_for(status)
        print({
            "good": "The revision is good.",
            "bad": "The revision is bad.",
            "skip": "It could not be determined if the revision is good or bad.",
            "abort": "Evaluation command returned 127 (command not found) - "
                     "aborting bisection.",
        }[evaluation])
        print()

        if args.find_good:
            # Looking for the first good revision inverts good and bad.
            # Skip and abort keep their meaning.
            evaluation = pyjj.Bisector.invert(evaluation)
        bisector.mark(commit.id, evaluation)

        # The evaluation command may have run `jj`, so reload.
        try:
            settings, ws, repo = _load(args)
        except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1

    print("Search complete. To discard any revisions created during search, run:")
    print(f"  jj op restore {initial_op[:12]}")

    target = "good" if args.find_good else "bad"
    if step.result == "abort":
        print("Error: Bisection aborted", file=sys.stderr)
        return 1
    if step.result == "indeterminate":
        print(f"Error: Could not find the first {target} revision. "
              "Was the input range empty?", file=sys.stderr)
        return 1

    found = list(step.commits)
    if len(found) == 1:
        print(f"The first {target} revision is: {_summary(found[0])}")
    else:
        print(f"The first {target} revisions are:")
        for commit in found:
            print(_summary(commit))
    return 0
