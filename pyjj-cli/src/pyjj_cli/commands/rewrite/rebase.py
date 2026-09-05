"""pyjj-cli rewrite command: rebase."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _wc_commit,
    complete_newline,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def rebase(args) -> int:
    try:
        settings, ws, repo = _load(args)
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

        tx = _start_transaction(repo, settings)
        # `-r` moves the targets themselves; `-s` and `-b` move roots and
        # everything under them. Only one of the two lists is ever set,
        # and jj checks whichever one it is.
        # `-A`/`-B` also rebase whatever followed the insertion point.
        _check_rewritable(
            tx, settings, target_commit_ids + target_root_ids + new_child_ids)
        tx.move_commits(
            target_commit_ids, target_root_ids, new_parent_ids, new_child_ids,
            skip_emptied=getattr(args, "skip_emptied", False),
            # jj abandons a divergent commit the destination already holds
            # with identical contents, unless this asks it not to.
            keep_divergent=getattr(args, "keep_divergent", False),
            simplify_parents=getattr(args, "simplify_parents", False))
        _finish(tx, "rebase commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _branch_roots(repo, settings, branches, new_parent_ids):
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
