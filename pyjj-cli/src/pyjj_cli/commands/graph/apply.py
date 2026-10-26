"""graph subcommand: apply — reshape the repository to match a graph.

Every step is a `move_commits`, the same primitive `rebase -r` uses --
but the whole reshape runs in one transaction, so it is all-or-nothing
by construction: anything going wrong drops the transaction and the
repository is exactly as it was, with no rollback path to maintain.
The conflict check runs before the commit too (`_finish`'s trial).
The pre-apply operation id is printed on success, so `op restore` is
one paste away even when everything worked.

Two refusals stand between a graph and a rewrite, and both are the
default:

- an immutable commit is not rewritten, the way every other rewrite
  command here refuses one;
- a conflict the reshape introduced drops the whole thing, since
  a graph describes topology and cannot have asked for one.
"""

from __future__ import annotations

import argparse
import json
import sys

import pyjj

from ..common import (
    CommandError,
    TrialStop,
    _check_rewritable,
    _finish,
    _load,
    _start_transaction,
)
from .resolve import read_graph, resolve


def _current_id(tx: pyjj.Transaction, settings: pyjj.UserSettings, change_key: str):
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


def apply(args: argparse.Namespace) -> int:
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

    # The way back, recorded before anything is written.
    before = repo.operation.id

    dry_run = getattr(args, "dry_run", False)
    allow_conflicts = getattr(args, "allow_conflicts", False)
    if allow_conflicts and getattr(args, "abort_on_conflict", False):
        print("Error: --allow-conflicts cannot be used with "
              "--abort-on-conflict", file=sys.stderr)
        return 2
    if dry_run:
        for key in abandons:
            print(f"would abandon {key}")
        for key, parents in steps:
            print(f"would rebase {key} onto {' '.join(parents)}")

    changes = {key: commit.change_id.reverse_hex()
               for key, commit in commits.items()}
    # Not write_tx: the load carries exit-2 mapping.
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
            tx.move_commits(target_commit_ids=[target], target_root_ids=[],
                            new_parent_ids=new_parents, new_child_ids=[])
            applied.append(key)

        parts = []
        if steps:
            parts.append(f"{len(steps)} rebased")
        if abandons:
            parts.append(f"{len(abandons)} abandoned")
        # A graph describes topology and cannot have asked for a
        # conflict, so refusing one is the default here.
        _finish(tx, f"graph apply: {' and '.join(parts)}",
                settings, ws, repo,
                trial=argparse.Namespace(dry_run=dry_run,
                                         abort_on_conflict=not allow_conflicts))
    except TrialStop as stop:
        if stop.exit_code and not dry_run:
            print("Hint: re-run with --allow-conflicts to keep the result",
                  file=sys.stderr)
        return stop.exit_code
    except (pyjj.JjError, CommandError) as e:
        # Nothing committed: the transaction is dropped, so the
        # repository is exactly as it was -- no rollback to run.
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    if getattr(args, "format", "text") == "json":
        print(json.dumps({"applied": applied, "rolled_back": False,
                          "before_op": before}, indent=2))
    else:
        print(f"Reshaped {len(applied)} commits.")
    print(f"Restore with: pyjj op restore {before}", file=sys.stderr)
    return 0
