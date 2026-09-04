"""pyjj-cli command: run — run a command across a set of revisions.

Mirrors `cli/src/commands/run.rs`. Each revision is checked out into a
scratch slot under `.jj/run/default/`, the command runs there, and the
resulting tree is written back onto the revision. `pyjj.RunPool` owns the
slots; this module owns the subprocess and the reporting.

Jobs run one at a time. `--jobs`/`run.jobs` still sizes the pool, because
the slot count is what decides how many build trees survive between
invocations, but nothing here runs in parallel yet. The repository result
does not depend on it: every command's tree lands in one map, and one
rewrite pass applies them all.

Unlike real `jj`, this does not refuse to rewrite immutable commits.
pyjj-cli has no immutability check anywhere yet, and `run` is not the
place to invent one.
"""
import os
import subprocess
import sys
from pathlib import Path

import pyjj

from .common import (CommandError, _check_rewritable, _finish, _load,
                     _resolve_all, _start_transaction)

# `revsets.run` in `cli/src/config/revsets.toml`.
_DEFAULT_REVSET = "reachable(@, mutable())"


def _resolve_jobs(settings, jobs) -> int:
    """Precedence: `--jobs`, the `run.jobs` config key, 1."""
    if jobs is not None:
        if jobs < 1:
            raise CommandError(
                f"invalid value for `--jobs`: {jobs} (must be a positive integer)")
        return jobs
    configured = settings.get_int("run.jobs")
    if configured is None:
        return 1
    if configured < 1:
        raise CommandError(
            f"invalid value for `run.jobs`: {configured} (must be a positive integer)")
    return configured


def _subdir(workspace_root: str, use_root: bool) -> str | None:
    """Where in each checked-out tree the command should run.

    `None` means the tree root (`--root`). Otherwise it is the invocation
    directory relative to the workspace root, so `pyjj run` from a
    subdirectory runs the command in the same subdirectory of every
    revision. A cwd outside the workspace gives the empty string, which
    is the root as well -- the same fallback jj takes.
    """
    if use_root:
        return None
    try:
        return str(Path(os.path.realpath(os.getcwd())).relative_to(
            os.path.realpath(workspace_root)))
    except ValueError:
        return ""


def _status_text(returncode: int) -> str:
    """Rust's `ExitStatus` Display, which is what jj's error message
    interpolates."""
    if returncode < 0:
        return f"signal: {-returncode}"
    return f"exit status: {returncode}"


def run(args) -> int:
    """`jj run [-r REVSETS] [-j JOBS] COMMAND [ARGS...]`."""
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        expressions = list(args.revisions or []) or [_DEFAULT_REVSET]
        commits = _resolve_all(repo, settings, expressions)
        jobs = _resolve_jobs(settings, args.jobs)

        # `argparse.REMAINDER` keeps a leading `--` separator; jj's clap
        # does not.
        extra = list(args.args or [])
        if extra and extra[0] == "--":
            extra = extra[1:]
        argv = [args.command] + extra
        spec = " ".join(argv)

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, commits)

        subdir = _subdir(ws.workspace_root, args.root)
        pool = pyjj.RunPool(ws.repo_path, jobs, args.clean)

        new_trees: dict[str, pyjj.TreeId] = {}
        for commit in commits:
            slot = pool.acquire(commit)
            try:
                exec_dir = slot.working_copy_dir
                if subdir:
                    exec_dir = os.path.join(exec_dir, subdir)
                if not os.path.isdir(exec_dir):
                    # The directory `pyjj run` was invoked from does not
                    # exist in this revision, so there is nothing to run.
                    slot.discard()
                    print(f"Skipped commit {commit.id.hex()}: directory does "
                          f"not exist: {subdir}", file=sys.stderr)
                    continue
                env = dict(os.environ)
                env["JJ_WORKSPACE_ROOT"] = slot.working_copy_dir
                env["JJ_CHANGE_ID"] = commit.change_id.reverse_hex()
                env["JJ_COMMIT_ID"] = commit.id.hex()
                try:
                    proc = subprocess.run(
                        argv, cwd=exec_dir, env=env, stdin=subprocess.DEVNULL,
                        capture_output=True, check=False)
                except OSError as e:
                    slot.finish(False)
                    raise CommandError(f"failed to run `{spec}`: {e}")
                dirty, tree_id = slot.finish(proc.returncode == 0)
            finally:
                slot.discard()

            # Buffered and emitted whole, so one revision's output never
            # interleaves with another's.
            if proc.stdout:
                sys.stdout.buffer.write(proc.stdout)
                sys.stdout.buffer.flush()
            if proc.stderr:
                sys.stderr.buffer.write(proc.stderr)
                sys.stderr.buffer.flush()
            if proc.returncode != 0:
                raise CommandError(
                    f"the command '{spec}' failed with "
                    f"{_status_text(proc.returncode)} for commit "
                    f"{commit.id.hex()}")
            if dirty and tree_id is not None:
                new_trees[commit.id.hex()] = tree_id

        if not new_trees:
            # The command changed nothing anywhere. jj drops the empty
            # transaction rather than committing it -- `finish()` in
            # `cli/src/cli_util.rs` returns early on `!has_changes()` --
            # so no operation is written, and the only trace is the
            # message every other no-op rewrite prints.
            print("Nothing changed.", file=sys.stderr)
            return 0

        count, reparented = tx.run_rewrite(
            [c.id for c in commits], new_trees, args.restore_descendants)
        print(f"Rewrote {count} commits", file=sys.stderr)
        if args.restore_descendants and reparented > 0:
            print(f"Rebased {reparented} descendant commits (while preserving "
                  f"their content)", file=sys.stderr)
        _finish(tx, f"run: rewrite {count} commits", settings, ws, repo)
        return 0
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
