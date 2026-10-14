"""pyjj-cli rewrite command: duplicate."""

from ..common import (
    _check_rewritable,
    CommandError,
    _finish,
    _resolve_all,
    _resolve_in_arg_order,
    command,
    write_tx,
)

@command
def duplicate(args) -> int:
    with write_tx(args) as (settings, ws, repo, tx):
        revsets = (list(args.revisions_pos)
                   + list(getattr(args, "revisions_opt", None) or [])) or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        parents, children = _placement(repo, settings, args)
        # The duplicates themselves are new commits, but `-A`/`-B` rebase
        # whatever followed the insertion point.
        _check_rewritable(tx, settings, children)
        copies = tx.duplicate(targets)
        if parents or children:
            # `tx.duplicate` always lands the copies beside their
            # originals; a placement flag then moves them where jj would
            # have put them in the first place.
            tx.move_commits([c.id for c in copies], [], parents, children)
        _finish(tx, "duplicate commit", settings, ws, repo)
        return 0


def _placement(repo, settings, args):
    """New parents and new children for the duplicates, from -o/-A/-B."""
    ontos = getattr(args, "ontos", None) or []
    afters = getattr(args, "insert_afters", None) or []
    befores = getattr(args, "insert_befores", None) or []
    if ontos and (afters or befores):
        raise CommandError("cannot combine --onto with --insert-after/--insert-before")
    if ontos:
        return [c.id for c in _resolve_in_arg_order(repo, settings, ontos)], []

    parents: list = []
    children: list = []
    if afters:
        parents = [c.id for c in _resolve_in_arg_order(repo, settings, afters)]
        expression = " | ".join(f"children({a})" for a in afters)
        children = [c.id for c in repo.revset(settings, expression)]
    if befores:
        before_commits = _resolve_in_arg_order(repo, settings, befores)
        children = [c.id for c in before_commits]
        if not afters:
            seen = {}
            for commit in before_commits:
                for pid in commit.parent_ids:
                    seen[pid.hex()] = pid
            parents = list(seen.values())
    return parents, children
