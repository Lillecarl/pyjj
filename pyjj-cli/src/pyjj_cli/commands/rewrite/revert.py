"""pyjj-cli rewrite command: revert."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _check_rewritable,
    _commit_location,
    _insert_between,
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

def revert(args) -> int:
    """`jj revert -r REV --onto REV` — apply reverse of revisions."""
    try:
        settings, ws, repo = _load(args)
        # Resolve revisions to revert (union of all -r)
        rev_args = getattr(args, "revisions", None) or []
        if not rev_args:
            print("Error: --revision is required", file=sys.stderr)
            return 2
        # _resolve_all expects list of revsets; each -r is a revset string
        targets = _resolve_all(repo, settings, rev_args)
        if not targets:
            print("No revisions to revert.")
            return 0
        # Sort in reverse topological order (children before parents) like real jj.
        # The revset engine already returns topological order (children before parents
        # for log_graph, but revset order is not guaranteed). For the simple case
        # of a linear chain, the order returned by _resolve_all (union) will be
        # the order of the input revsets, not topological. We can sort by
        # using the repo's log_graph or by checking parent relationships.
        # Simplest: sort by commit date or just reverse the list if it's linear.
        # For now, sort by trying to order so that descendants come before ancestors
        # by checking if one is ancestor of another via revset.
        # If we can't determine, just reverse the input order which matches
        # jj's "reverse topological" for the common case of passing parents first.
        # We can attempt to use the repo's revset to get topological order:
        try:
            # Build a revset that includes all targets and get their order
            union = " | ".join(f"({r})" for r in rev_args)
            ordered = repo.revset(settings, union)
            # ordered is already topological (children before parents) per log_graph?
            # Reverse to get reverse topological (parents before children) then reverse again?
            # Actually we want reverse topological for revert: children first, so that
            # each revert is applied on top of the previous. That is the same as
            # topological order where children are first.
            # So we can just use ordered as is, but ensure it matches targets set.
            id_to_commit = {c.id.hex(): c for c in targets}
            # Filter ordered to only those in targets, preserving ordered's sequence
            ordered_targets = [id_to_commit[c.id.hex()] for c in ordered if c.id.hex() in id_to_commit]
            # If ordered_targets has same length, use it; else fallback to original
            if len(ordered_targets) == len(targets):
                targets = ordered_targets
        except Exception:
            pass

        # Determine destination: --onto / --destination / --insert-after / --insert-before
        ontos = getattr(args, "ontos", None) or []
        dests = getattr(args, "destinations", None) or []
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []
        plain = list(ontos) + list(dests)
        if not (plain or afters or befores):
            print("Error: --onto, --insert-after or --insert-before is required", file=sys.stderr)
            return 2
        if plain and (afters or befores):
            print("Error: --onto cannot be used with --insert-after or "
                  "--insert-before", file=sys.stderr)
            return 2

        # `-A` and `-B` combine: together they name both sides of the
        # insertion point directly.
        new_parent_ids, new_child_ids = _commit_location(
            repo, settings, plain, afters, befores)
        if not new_parent_ids:
            print("Error: No revisions found to use as parent", file=sys.stderr)
            return 1

        tx = repo.start_transaction(settings)
        # `-A`/`-B` rebase whatever followed the insertion point.
        _check_rewritable(tx, settings, new_child_ids)
        # Chain reverts in the determined order (which should be reverse topological,
        # i.e. children first). The first revert is onto new_parent_ids, subsequent
        # ones are onto the previous revert's commit.
        current_parents = new_parent_ids
        last_revert = None
        for commit in targets:
            builder = tx.revert_commit(commit, current_parents)
            # Generate description like jj's default templates.revert_description:
            #   'Revert "' ++ description.first_line() ++ '"\n\nThis reverts commit ' ++ commit_id ++ '.\n'
            first_line = commit.description.splitlines()[0] if commit.description else ""
            desc = f'Revert "{first_line}"\n\nThis reverts commit {commit.id.hex()}.\n'
            builder.set_description(desc)
            last_revert = builder.write(repo)
            current_parents = [last_revert.id]
            # For insert-after/before, the new_child_ids should be rebased onto the final revert chain.
            # We will handle that after the loop by rebasing original children.

        if last_revert is None:
            print("No revisions to revert.")
            return 0

        # The reverts form a chain, so the children hang from its head.
        if new_child_ids:
            _insert_between(tx, repo, new_parent_ids, new_child_ids,
                            last_revert.id)

        # If the source was @ and we created a new commit, the working copy should follow?
        # _finish will handle rebase_descendants and checkout.
        _finish(tx, f"revert {rev_args[0] if rev_args else ''}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
