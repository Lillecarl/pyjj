"""pyjj-cli rewrite command: split."""
import subprocess
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    _commit_location,
    CommandError,
    _finish,
    _load,
    _resolve_one,
    complete_newline,
    _run_bulk_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
)

def split(args) -> int:
    try:
        settings, ws, repo = _load(args)
        parallel = getattr(args, "parallel", False)
        ontos = ((getattr(args, "ontos", None) or [])
                 + (getattr(args, "destinations", None) or []))
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []
        # A placement flag sends the selected half somewhere else, so it
        # cannot also make the two halves siblings. Worded like clap,
        # which reports these conflicts (lowercase `error:`, usage,
        # `--help` trailer).
        moving = bool(ontos or afters or befores)
        if moving and parallel:
            placed = ("--onto <REVSETS>" if ontos
                      else "--insert-after <REVSETS>" if afters
                      else "--insert-before <REVSETS>")
            print(f"error: the argument '--parallel' cannot be used with "
                  f"'{placed}'", file=sys.stderr)
            print("\nUsage: jj split --parallel <FILESETS>...",
                  file=sys.stderr)
            print("\nFor more information, try '--help'.",
                  file=sys.stderr)
            return 2
        if ontos and (afters or befores):
            other = ("--insert-after <REVSETS>" if afters
                     else "--insert-before <REVSETS>")
            print(f"error: the argument '--onto <REVSETS>' cannot be used "
                  f"with '{other}'", file=sys.stderr)
            print("\nUsage: jj split --onto <REVSETS> <FILESETS>...",
                  file=sys.stderr)
            print("\nFor more information, try '--help'.",
                  file=sys.stderr)
            return 2

        target = _resolve_one(repo, settings, args.revision or "@")

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [target])
        new_parent_ids: list = []
        new_child_ids: list = []
        if moving:
            new_parent_ids, new_child_ids = _commit_location(
                repo, settings, ontos, afters, befores)
            # The commits that followed the insertion point get rebased,
            # so they have to be rewritable.
            _check_rewritable(tx, settings, new_child_ids)
            if not new_parent_ids:
                print("Error: No revisions found to use as parent",
                      file=sys.stderr)
                return 1
        if args.paths_pos:
            first_builder = tx.split_selected(target, list(args.paths_pos))
        else:
            # The diff-editor path: select changes by editing the right
            # directory. Upstream order applies the diff selection first,
            # then the description.
            if not args.tool:
                print("Error: no diff editor specified; pass --tool",
                      file=sys.stderr)
                return 2
            parent = repo.get_commit(target.parent_ids[0])
            changed = _changed_files(repo, settings, parent, target)
            before = {p: b for p, (b, _a) in changed.items()}
            after = {p: a for p, (_b, a) in changed.items()}
            selections = _run_diff_tool(settings, args.tool, before, after)
            if _selection_is_empty(selections, before):
                print("No changes selected.")
                return 1
            first_builder = tx.split_selected_edited(target, selections)

        forced_editor = getattr(args, "editor", False)
        if args.message is None or forced_editor:
            # Since jj 0.46 both halves share one editor session: two
            # `JJ: describe` sections in one buffer, not one session per
            # half. The seeds are what each half would keep untouched --
            # `-m` (completed) for the selected changes, the revision's
            # own description for the remainder.
            first_seed = (complete_newline(args.message)
                          if args.message is not None
                          else target.description)
            edited = _run_bulk_editor(settings, [
                ("1", "Enter a description for the selected changes.",
                 first_seed),
                ("2", "Enter a description for the remaining changes.",
                 target.description),
            ])
            first_description = edited["1"]
            second_description = edited["2"]
        else:
            first_description = complete_newline(args.message)
            second_description = target.description

        if moving:
            # The half that stays where `target` was keeps its change id,
            # and the half that moves takes a fresh one. Clearing the
            # rewrite source leaves the remainder as the only commit that
            # claims to rewrite `target`, so descendants and bookmarks
            # follow it rather than the commit that left.
            first_builder = (first_builder
                             .clear_rewrite_source()
                             .generate_new_change_id())
        first = first_builder.set_description(first_description).write(repo)
        if parallel:
            second = (tx.split_remainder_parallel(target, first)
                      .set_description(second_description).write(repo))
            # Whatever followed the split now sits on both halves, first
            # one first -- a merge's parent order is part of its id.
            children = repo.revset(settings, f"children({target.id.hex()})")
            if children:
                tx.move_commits([c.id for c in children], [],
                                [first.id, second.id], [])
        else:
            second = (tx.split_remainder(target, first,
                                         new_change_id=not moving)
                      .set_description(second_description).write(repo))
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        if moving:
            # jj settles the descendants onto the remainder first, then
            # moves the selected half away -- which pulls the remainder
            # back down onto the parents `target` used to have. Doing it
            # in the other order would move a commit whose descendants
            # still hang off the old one.
            #
            # A placement revision that is itself a descendant of `target`
            # has a new commit id by then, so it is tracked by change id,
            # which a rebase preserves.
            parent_changes = _change_ids(repo, new_parent_ids)
            child_changes = _change_ids(repo, new_child_ids)
            tx.rebase_descendants(delete_abandoned_bookmarks=False)
            tx.move_commits(
                [first.id], [],
                _by_change_ids(tx, settings, parent_changes),
                _by_change_ids(tx, settings, child_changes))
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def _change_ids(repo, commit_ids):
    """The change id behind each commit id, in order."""
    return [repo.get_commit(commit_id).change_id.reverse_hex()
            for commit_id in commit_ids]


def _by_change_ids(tx, settings, change_hexes):
    """Back to commit ids, after a rebase may have moved them. The query
    runs against the transaction, which is the only place the rebased
    commits exist yet."""
    ids = []
    for change_hex in change_hexes:
        ids.extend(tx.revset(settings, change_hex))
    return ids
