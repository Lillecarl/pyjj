"""graph subcommand: apply — reshape the repository to match a graph.

Every step is a `move_commits`, the same primitive `rebase -r` uses --
but the whole reshape runs in one transaction, so it is all-or-nothing
by construction: anything going wrong drops the transaction and the
repository is exactly as it was, with no rollback path to maintain.
(Only a conflict discovered *after* committing needs
`op restore`-backed rollback, since the result is already written by
then.) The pre-apply operation id is also printed on success, so
`op restore` is one paste away even when everything worked.

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


def _current_id(tx, settings, change_key: str):
    """The commit a change id names in the transaction's own view.

    Change ids survive rewrites, so this tracks a commit through the
    plan's earlier steps where a commit id would go stale behind its
    hidden predecessor. Anything but exactly one match is a clean
    failure with nothing written yet.
    """
    matches = tx.revset(settings, change_key)
    if len(matches) != 1:
        raise CommandError(
            f"change {change_key} names {len(matches)} commits mid-apply")
    return matches[0]


def apply(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        steps, abandons, commits = resolve(repo, settings,
                                           read_graph(getattr(args, "file")))
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not steps and not abandons:
        print("Nothing to do: the repository already matches the graph.")
        return 0

    # The rollback point, recorded before anything is written.
    before = repo.operation.id

    if getattr(args, "dry_run", False):
        for key in abandons:
            print(f"would abandon {key}")
        for key, parents in steps:
            print(f"would rebase {key} onto {' '.join(parents)}")
        return 0

    changes = {key: commit.change_id.reverse_hex()
               for key, commit in commits.items()}
    tx = _start_transaction(repo, settings)
    try:
        if not getattr(args, "ignore_immutable", False):
            # The same guard `rebase` runs. Without it a graph is a
            # way around the protection rather than a use of it.
            targets = [commits[key].id for key, _ in steps]
            targets += [commits[key].id for key in abandons]
            _check_rewritable(tx, settings, targets)
        for key in abandons:
            tx.abandon_commit(commits[key])
        applied = list(abandons)
        for key, parents in steps:
            target = _current_id(tx, settings, changes[key])
            new_parents = [_current_id(tx, settings, changes[parent])
                           for parent in parents]
            tx.move_commits([target], [], new_parents, [])
            applied.append(key)

        parts = []
        if steps:
            parts.append(f"{len(steps)} rebased")
        if abandons:
            parts.append(f"{len(abandons)} abandoned")
        _finish(tx, f"graph apply: {' and '.join(parts)}",
                settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        # Nothing committed: the transaction is dropped, so the
        # repository is exactly as it was -- no rollback to run.
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    try:
        repo = ws.load_at_head()
        if not getattr(args, "allow_conflicts", False):
            conflicted = _conflicted(repo, settings, list(commits))
            if conflicted:
                _rollback(
                    ws, settings, before,
                    "the reshape left "
                    + ", ".join(sorted(conflicted)[:4])
                    + (" and others" if len(conflicted) > 4 else "")
                    + " in conflict", len(applied),
                    hint="re-run with --allow-conflicts to keep the result")
                return 1
    except (pyjj.JjError, CommandError) as e:
        _rollback(ws, settings, before, f"{getattr(e, 'message', e)}",
                  len(applied))
        return 1
    except Exception as e:  # noqa: BLE001 -- a half-reshaped repository
        # is the state worth never leaving behind, even for an error
        # this module did not predict.
        _rollback(ws, settings, before,
                  f"unexpected {type(e).__name__}: {e}", len(applied))
        raise

    if getattr(args, "format", "text") == "json":
        print(json.dumps({"applied": applied, "rolled_back": False,
                          "before_op": before}, indent=2))
    else:
        print(f"Reshaped {len(applied)} commits.")
    print(f"Restore with: pyjj op restore {before}", file=sys.stderr)
    return 0


def _rollback(ws, settings, operation_id: str, why: str, applied: int,
              hint: str | None = None) -> None:
    """Put the repository back where it started, and say so.

    Only the conflict path still needs this: mid-apply failures drop
    their transaction unwritten, but a conflict is found after
    committing. A partial reshape is the state worth never leaving
    behind either way.
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
              f"Restore it by hand with `pyjj op restore {operation_id}`",
              file=sys.stderr)
        return
    print(f"Rolled back {applied} applied step(s); the repository is as "
          "it was.", file=sys.stderr)
    if hint:
        print(f"Hint: {hint}", file=sys.stderr)
