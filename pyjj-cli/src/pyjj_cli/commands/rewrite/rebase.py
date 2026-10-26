"""pyjj-cli rewrite command: rebase."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _check_rewritable,
    _finish,
    _resolve_all,
    _resolve_in_arg_order,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

@command
def rebase(args: argparse.Namespace) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        # Determine source mode: -r (commit_ids), -s (root_ids), -b (branch roots)
        revisions = getattr(args, "revisions", None)
        sources = getattr(args, "sources", None)
        branches = getattr(args, "branches", None)
        # Count how many source modes were given
        mode_count = sum(1 for m in (revisions, sources, branches) if m)
        if mode_count == 0:
            # jj's default is `-b @`, which moves the roots of @'s branch
            # relative to the destination -- not `-s @`, which would move
            # only @ itself.
            branches = ["@"]
            mode_count = 1
        if mode_count > 1:
            print("Error: specify only one of -r, -s, -b", file=sys.stderr)
            return 2
        target_commit_ids: list[pyjj.CommitId]
        target_root_ids: list[pyjj.CommitId]
        if revisions:
            targets = _resolve_all(repo, settings, revisions)
            target_commit_ids = [c.id for c in targets]
            target_root_ids = []
        elif sources:
            roots = _resolve_all(repo, settings, sources)
            target_root_ids = [c.id for c in roots]
            target_commit_ids = []
        else:  # branches
            # `-b` names any commit in a branch; the commits that actually
            # move are the roots of that branch relative to the
            # destination. Those roots need the destination, so they are
            # computed once it is known, below.
            target_root_ids = []
            target_commit_ids = []

        # Destinations: -d/--destination, -o/--onto, -A/--insert-after, -B/--insert-before
        dests = getattr(args, "destinations", None) or []
        ontos = getattr(args, "ontos", None) or []
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []

        # Expand -o as alias for -d
        new_parent_ids: list[pyjj.CommitId] = []
        new_child_ids: list[pyjj.CommitId] = []

        # Collect plain destinations (-d / -o)
        plain_dests = list(dests) + list(ontos)
        if plain_dests:
            if afters or befores:
                print("Error: cannot combine -d/-o with -A/-B", file=sys.stderr)
                return 2
            dest_commits = _resolve_in_arg_order(repo, settings, plain_dests)
            new_parent_ids = [c.id for c in dest_commits]
            new_child_ids = []
        elif afters:
            # -A: insert after -> new parents = after, new children = children(after)
            after_commits = _resolve_in_arg_order(repo, settings, afters)
            new_parent_ids = [c.id for c in after_commits]
            # Find children of after commits via revset
            try:
                children_expr = " | ".join(f"children({a})" for a in afters)
                children = repo.revset(settings, children_expr)
                new_child_ids = [c.id for c in children]
            except pyjj.JjError:
                new_child_ids = []
        elif befores:
            # -B: insert before -> new children = before, new parents = parents(before)
            before_commits = _resolve_in_arg_order(repo, settings, befores)
            new_child_ids = [c.id for c in before_commits]
            parents_set: dict[str, pyjj.Commit] = {}
            for c in before_commits:
                for pid in c.parent_ids:
                    try:
                        p = repo.get_commit(pid)
                        parents_set[pid.hex()] = p
                    except pyjj.JjError:
                        pass
            new_parent_ids = [c.id for c in parents_set.values()]
        else:
            print("Error: no destination specified (use -d, -o, -A or -B)", file=sys.stderr)
            return 2

        if branches:
            target_root_ids = _branch_roots(repo, settings, branches, new_parent_ids)
            if not target_root_ids:
                print("Nothing changed.", file=sys.stderr)
                return 0

        # `-r` moves the targets themselves; `-s` and `-b` move roots and
        # everything under them. Only one of the two lists is ever set,
        # and jj checks whichever one it is.
        # `-A`/`-B` also rebase whatever followed the insertion point.
        _check_rewritable(
            tx, settings, target_commit_ids + target_root_ids + new_child_ids)
        stats = tx.move_commits(
            target_commit_ids=target_commit_ids, target_root_ids=target_root_ids,
            new_parent_ids=new_parent_ids, new_child_ids=new_child_ids,
            skip_emptied=getattr(args, "skip_emptied", False),
            # jj abandons a divergent commit the destination already holds
            # with identical contents, unless this asks it not to.
            keep_divergent=getattr(args, "keep_divergent", False),
            simplify_parents=getattr(args, "simplify_parents", False))
        dry_run = getattr(args, "dry_run", False)
        abort_on_conflict = getattr(args, "abort_on_conflict", False)
        if dry_run or abort_on_conflict:
            tx.rebase_descendants()
            conflicted = _new_conflicts(repo, tx, settings)
            if dry_run:
                rebased = (stats.num_rebased_targets
                           + stats.num_rebased_descendants)
                print(f"Would rebase {rebased} commits.")
                if conflicted:
                    print(f"New conflicts would appear in "
                          f"{len(conflicted)} commits:")
                    print("\n".join(conflicted))
            elif conflicted:
                print(f"Error: the rebase would leave {len(conflicted)} "
                      f"commits in conflict:", file=sys.stderr)
                print("\n".join(conflicted), file=sys.stderr)
                print("Nothing changed.", file=sys.stderr)
            # Returning before `_finish` drops the transaction unwritten.
            if conflicted and abort_on_conflict:
                return 1
            if dry_run:
                return 0
        _finish(tx, "rebase commit", settings, ws, repo)
        return 0


def _new_conflicts(repo: pyjj.ReadonlyRepo, tx: pyjj.Transaction,
                   settings: pyjj.UserSettings) -> list[str]:
    """`  <change id> <description>` for each commit the rebase put in
    conflict, as jj's "New conflicts appeared" lists them.

    Matched by change id, because the rebase rewrote the commit ids. A
    commit that was already conflicted does not count. Only mutable
    commits are scanned: nothing immutable can have been rewritten.
    """
    expression = "conflicts() & mutable()"
    before = {c.change_id.reverse_hex() for c in repo.revset(settings, expression)}
    lines = []
    for commit_id in tx.revset(settings, expression):
        # The store holds the transaction's commits already; only the
        # base repo's index lacks them.
        commit = repo.get_commit(commit_id)
        change = commit.change_id.reverse_hex()
        if change in before:
            continue
        first_line = (commit.description.splitlines() or [""])[0]
        lines.append(f"  {change[:8]} {first_line or '(no description set)'}")
    return lines


def _branch_roots(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings,
                  branches: Iterable[str], new_parent_ids: Iterable[pyjj.CommitId]):
    """`roots(destination..branch)`: the commits `jj rebase -b` moves.

    A branch commit that is already an ancestor of the destination stays
    where it is, so only the roots of the part that is *not* yet below
    the destination get rebased. Without this, `-b` would behave like
    `-s` and drag the named commit off its own branch.
    """
    branch_expression = " | ".join(f"({b})" for b in branches)
    dest_expression = " | ".join(p.hex() for p in new_parent_ids)
    expression = f"roots(({dest_expression})..({branch_expression}))"
    return [c.id for c in repo.revset(settings, expression)]
