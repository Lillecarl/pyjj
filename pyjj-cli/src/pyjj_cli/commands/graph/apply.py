"""graph subcommand: apply — reshape the repository to match a graph.

Every step is a `move_commits`, the same primitive `rebase -r` uses.
The reshape is all-or-nothing: the operation the repository sat at
before is recorded first, and anything that goes wrong restores it, so
a half-applied graph is not a state this can leave behind.

Two refusals stand between a graph and a rewrite, and both are the
default:

- an immutable commit is not rewritten, the way every other rewrite
  command here refuses one;
- a conflict the reshape introduced rolls the whole thing back, since
  a graph describes topology and cannot have asked for one.
"""
import json
import sys

import pyjj

from ..common import (
    CommandError,
    _check_rewritable,
    _finish,
    _load,
    _start_transaction,
)
from .resolve import read_graph, resolve


def _conflicted(repo, settings, keys) -> list[str]:
    """Which of `keys` name a commit carrying a conflict now."""
    out = []
    for key in keys:
        try:
            commit = repo.resolve_single(settings, key)
        except pyjj.JjError:
            # The reshape can abandon a commit; that is not a conflict.
            continue
        if commit.has_conflict:
            out.append(key)
    return out


def apply(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        steps, commits = resolve(repo, settings,
                                 read_graph(getattr(args, "file")))
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not steps:
        print("Nothing to do: the repository already matches the graph.")
        return 0

    # The rollback point, recorded before anything is written.
    before = repo.operation.id

    if getattr(args, "dry_run", False):
        for key, parents in steps:
            print(f"would rebase {key} onto {' '.join(parents)}")
        return 0

    applied = []
    # Everything after the first write is inside this: a rollback that
    # only ran for the errors this module predicted would leave a
    # half-reshaped repository behind for the ones it did not. A
    # mistake here is a wrong graph, and the repository should survive
    # one.
    try:
        for key, parents in steps:
            repo = ws.load_at_head()
            target = repo.resolve_single(settings, key)
            new_parents = [repo.resolve_single(settings, parent).id
                           for parent in parents]
            tx = _start_transaction(repo, settings)
            if not getattr(args, "ignore_immutable", False):
                # The same guard `rebase` runs. Without it a graph is a
                # way around the protection rather than a use of it.
                _check_rewritable(tx, settings, [target.id])
            tx.move_commits([target.id], [], new_parents, [])
            _finish(tx, f"graph apply: rebase {key}", settings, ws, repo)
            applied.append(key)

        repo = ws.load_at_head()
        if not getattr(args, "allow_conflicts", False):
            conflicted = _conflicted(repo, settings, list(commits))
            if conflicted:
                _rollback(
                    ws, settings, before,
                    "the reshape left "
                    + ", ".join(sorted(conflicted)[:4])
                    + (" and others" if len(conflicted) > 4 else "")
                    + " in conflict", applied,
                    hint="re-run with --allow-conflicts to keep the result")
                return 1
    except (pyjj.JjError, CommandError) as e:
        _rollback(ws, settings, before, f"{getattr(e, 'message', e)}", applied)
        return 1
    except Exception as e:  # noqa: BLE001 -- see the comment above
        _rollback(ws, settings, before,
                  f"unexpected {type(e).__name__}: {e}", applied)
        raise

    if getattr(args, "format", "text") == "json":
        print(json.dumps({"applied": applied, "rolled_back": False}, indent=2))
    else:
        print(f"Reshaped {len(applied)} commits.")
    return 0


def _rollback(ws, settings, operation_id: str, why: str, applied,
              hint: str | None = None) -> None:
    """Put the repository back where it started, and say so.

    A partial reshape is the state worth never leaving behind: half a
    graph is neither the shape that was asked for nor the one that was
    there.
    """
    print(f"Error: {why}", file=sys.stderr)
    try:
        repo = ws.load_at_head()
        target = repo.load_operation(operation_id)
        tx = _start_transaction(repo, settings)
        tx.restore_operation(target)
        _finish(tx, "graph apply: roll back", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: rollback failed: {getattr(e, 'message', e)}. "
              f"Restore it by hand with `pyjj op restore {operation_id[:12]}`",
              file=sys.stderr)
        return
    print(f"Rolled back {len(applied)} applied step(s); the repository is as "
          "it was.", file=sys.stderr)
    if hint:
        print(f"Hint: {hint}", file=sys.stderr)
