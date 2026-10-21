"""pyjj-cli rewrite command: squash."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from ..common import (
    CommandError,
    _changed_files,
    _check_rewritable,
    _finish,
    _prepare_insertion,
    _resolve_all,
    _resolve_one,
    _rev,
    _run_diff_tool,
    _run_editor,
    _split_changed,
    command,
    complete_newline,
    write_tx,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    import pyjj

# What jj's clap refuses outright, as `(flag, dest, incompatible with)`.
# `-r` names one commit and its parent, so nothing that names a
# destination fits beside it; `-o` names the parents directly, so an
# insertion point does not.
_CONFLICTS = (
    ("--from", "from_", ("-r/--revision", "revision")),
    ("--into", "into", ("-r/--revision", "revision")),
    ("--onto", "ontos", ("-r/--revision", "revision")),
    ("--onto", "ontos", ("--into", "into")),
    ("--insert-after", "insert_afters", ("-r/--revision", "revision")),
    ("--insert-after", "insert_afters", ("--into", "into")),
    ("--insert-after", "insert_afters", ("--onto", "ontos")),
    ("--insert-before", "insert_befores", ("-r/--revision", "revision")),
    ("--insert-before", "insert_befores", ("--into", "into")),
    ("--insert-before", "insert_befores", ("--onto", "ontos")),
    ("--message", "message", ("-u/--use-destination-message",
                              "use_destination_message")),
)


def _conflicting_flag(args: argparse.Namespace) -> str | None:
    """The first pair of flags jj would refuse together, if any."""
    for name, dest, (other_name, other_dest) in _CONFLICTS:
        if getattr(args, dest, None) and getattr(args, other_dest, None):
            return f"{name} cannot be used with {other_name}"
    return None


@command
def squash(args: argparse.Namespace) -> int:
    refusal = _conflicting_flag(args)
    if refusal is not None:
        print(f"Error: {refusal}", file=sys.stderr)
        return 2
    try:
        with write_tx(args) as (settings, ws, repo, tx):
            ontos = list(getattr(args, "ontos", None) or [])
            afters = list(getattr(args, "insert_afters", None) or [])
            befores = list(getattr(args, "insert_befores", None) or [])
            # The experimental UI: `-o`/`-A`/`-B` squash into a commit that
            # does not exist yet, so the command creates one and places it.
            inserting = bool(ontos or afters or befores)

            sources, dest = _sources_and_destination(
                args, repo, settings, inserting)
            if len(sources) != 1:
                raise CommandError(
                    "squashing multiple source revisions is not supported yet")
            source = sources[0]
            # jj names the transaction after the commits it was asked for,
            # before an insertion rebases any of them.
            squashed = f"squash commit {source.id.hex()}"

            description = _description(args, settings, source, dest)

            _check_rewritable(tx, settings, [source] if dest is None
                              else [source, dest])
            if dest is None:
                dest, source = _place_new_commit(
                    tx, repo, settings, source, ontos, afters, befores)

            keep_emptied = getattr(args, "keep_emptied", False)
            tool = getattr(args, "tool", None)
            if tool:
                builder = tx.squash_edited(
                    source, dest, _selected(repo, settings, tool, source),
                    keep_emptied=keep_emptied)
            else:
                builder = tx.squash(source, dest,
                                    paths=getattr(args, "filesets", None) or None,
                                    keep_emptied=keep_emptied)
            if builder is None:
                if tool:
                    # A selection that moved nothing is a mistake rather than
                    # a no-op: the reader was asked to choose and chose none.
                    raise CommandError("No changes selected")
                if not inserting:
                    print("Nothing changed.", file=sys.stderr)
                    return 0
                # The placement still created a commit, so the operation is
                # not empty even though nothing moved into it.
            else:
                builder = builder.set_description(description)
                if inserting:
                    # Forget the empty commit the placement created. It is a
                    # step nobody asked for, and an evolog naming it would
                    # read as a history the user never made.
                    builder = builder.set_predecessors(
                        [p for p in builder.predecessors()
                         if p.hex() != dest.id.hex()])
                builder.write(repo)
            # jj words this by where the changes landed. A destination that
            # already existed -- `--into`, or the source's parent -- reads
            # `squash commits into <id>`; a destination the command creates
            # reads `squash commit <id>`.
            _finish(tx, squashed if inserting
                    else f"squash commits into {dest.id.hex()}",
                    settings, ws, repo)
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def _selected(repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, tool: str, source: pyjj.Commit):
    """What a diff editor chose to move, per path.

    The tool edits the source's own diff: left is the source's parent,
    right is the source. Whatever the right side holds when the tool
    exits is what moves, so leaving it alone moves everything.
    """
    parent = repo.get_commit(source.parent_ids[0])
    before, after = _split_changed(_changed_files(repo, settings, parent, source))
    return _run_diff_tool(settings, tool, before, after)


def _sources_and_destination(args: argparse.Namespace, repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings, inserting: bool):
    """The commits to squash from, and the one to squash into.

    The destination is `None` when a placement flag asks for a commit
    that does not exist yet. Note the two defaults jj uses: `--from`
    defaults to `@` and `--into` defaults to `@` as well, so `jj squash
    --from X` moves X into the working copy -- it is only the plain
    `-r` form that squashes into the source's own parent.
    """
    if args.from_ or args.into or inserting:
        sources = _resolve_all(repo, settings, list(args.from_ or ["@"]))
        if inserting:
            return _oldest_first(sources), None
        dest = _resolve_one(repo, settings, _rev(args, "into"))
        # A destination named on both sides is not a source.
        sources = [c for c in sources if c.id.hex() != dest.id.hex()]
        return _oldest_first(sources), dest
    source = _resolve_one(repo, settings, _rev(args, "revision"))
    if len(source.parent_ids) != 1:
        raise CommandError(
            "Cannot squash merge commits without a specified destination")
    return [source], repo.get_commit(source.parent_ids[0])


def _oldest_first(sources: Sequence[pyjj.Commit]) -> list[pyjj.Commit]:
    """jj applies the oldest source first, which avoids building a
    conflict that the next source would only resolve again."""
    return list(reversed(sources))


def _description(args: argparse.Namespace, settings: pyjj.UserSettings,
                 source: pyjj.Commit, dest: pyjj.Commit | None) -> str:
    """The description the squashed commit ends up with.

    `-m` gives it outright and `-u` keeps the destination's. With
    neither, a single non-empty side wins and two non-empty sides open
    the combining editor, whose template is destination-block-first. A
    placement leaves only one side, since the commit it creates has no
    description of its own.
    """
    if args.message is not None:
        text = complete_newline(args.message)
    elif args.use_destination_message:
        text = dest.description if dest is not None else ""
    else:
        sides = [source] if dest is None else [source, dest]
        candidates = [c.description for c in sides if c.description]
        if dest is not None and len(candidates) > 1:
            # Two descriptions cannot be joined without a choice, so the
            # editor opens whether or not `--editor` asked for it.
            combined = (
                "JJ: Description from the destination commit:\n"
                + dest.description
                + "\nJJ: Description from source commit:\n"
                + source.description
            )
            return _run_editor(settings, combined)
        text = candidates[0] if candidates else ""
    if getattr(args, "editor", False):
        return _run_editor(settings, text)
    return text


def _place_new_commit(tx: pyjj.Transaction, repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings,
                      source: pyjj.Commit, ontos: Sequence[str], afters: Sequence[str],
                      befores: Sequence[str]):
    """The empty commit `-o`/`-A`/`-B` squash into, and the source as it
    stands once that commit is in the graph.

    An insertion rebases whatever followed the insertion point, and the
    source is usually one of those: `@` sits below almost anywhere a
    reader would insert. Squashing the commit as it was before the
    rebase would write a second version of it, so the source is read
    back by its change id, which a rebase keeps.
    """
    parents, children = _prepare_insertion(
        tx, repo, settings, ontos, afters, befores)
    dest = tx.new_commit(settings, parents).write(repo)
    if not children:
        return dest, source
    change = source.change_id.reverse_hex()
    tx.move_commits(target_commit_ids=[dest.id], target_root_ids=[],
                    new_parent_ids=parents, new_child_ids=children)
    moved = tx.revset(settings, change)
    return dest, repo.get_commit(moved[0]) if moved else source
