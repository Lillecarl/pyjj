"""operation subcommand: op diff — what changed between two operations.

Mirrors `cli/src/commands/operation/diff.rs`. The whole comparison lives
in `ReadonlyRepo.operation_diff()`; this module only names the two
operations and prints the result.

The changed commits are drawn on their own graph, which is why
`ReadonlyRepo.commits_graph()` exists: some of them are hidden, and no
revset expression reaches those. The `--patch` diff bodies are not
drawn yet.
"""
import sys

import pyjj

from ..common import (
    CommandError,
    _bookmarks_by_commit,
    _commit_summary,
    _format_timestamp,
    _load,
    _resolve_operation,
)


def _op_summary(op) -> str:
    """jj's `templates.op_summary`: the id, when it ended, and what it
    did. The root operation says `root()` where a time would go."""
    when = ("root()" if not op.parent_ids
            else f"({_format_timestamp(op.end_time)})")
    return " ".join(part for part in (op.id[:12], when, op.description) if part)


def _summary(repo, settings, commit) -> str:
    """A commit as `op diff` prints it, bookmarks and all.

    jj renders these with its `commit_summary` template, which names the
    bookmarks on a commit -- `movruppx 1a949896 main | one`. Dropping
    them would lose the one part of the line that says which branch an
    operation moved.
    """
    bookmarks = _bookmarks_by_commit(repo).get(commit.id.hex(), [])
    return _commit_summary(repo, settings, commit, bookmarks)


def _print_target(repo, settings, summary, added: bool) -> None:
    """One side of a changed ref, `+` for the new state, `-` for the old."""
    sign = "+" if added else "-"
    prefix = f"{summary.state} " if summary.state else ""
    if summary.absent:
        print(f"{sign} {prefix}(absent)")
        return
    if summary.conflict:
        for commit in summary.commits:
            print(f"{sign} {prefix}(added) {_summary(repo, settings, commit)}")
        for commit in summary.removed_commits:
            print(f"{sign} {prefix}(removed) {_summary(repo, settings, commit)}")
        return
    for commit in summary.commits:
        print(f"{sign} {prefix}{_summary(repo, settings, commit)}")


def _print_ref_section(repo, settings, heading: str, changes) -> None:
    if not changes:
        return
    print()
    print(heading)
    for change in changes:
        name = change.name
        if change.remote:
            name = f"{name}@{change.remote}"
        print(f"{name}:")
        _print_target(repo, settings, change.after, True)
        _print_target(repo, settings, change.before, False)


def _change_key(change):
    """The commit id jj keys a modified change by.

    A change that still exists is keyed by its new commit; one that was
    abandoned is keyed by the commit that went away.
    """
    commits = change.added or change.removed
    return commits[0].id


def _print_changed_commits(repo, settings, changes, no_graph: bool) -> None:
    """The `Changed commits:` block, with or without its graph."""
    def summary_lines(change):
        return (
            [f"+ {_summary(repo, settings, commit)}"
             for commit in change.added]
            + [f"- {_summary(repo, settings, commit)}"
               for commit in change.removed]
        )

    if no_graph:
        for change in changes:
            for line in summary_lines(change):
                print(line)
        return

    # The graph is over the changed commits alone, so its order is its
    # own -- topologically grouped -- rather than the flat order above.
    by_id = {_change_key(change).hex(): change for change in changes}
    renderer = pyjj.GraphRenderer()
    for node in repo.commits_graph([_change_key(change) for change in changes]):
        node_id = node.commit.id.hex()
        edges = [(edge.target.hex(), edge.edge_type) for edge in node.edges]
        text = "\n".join(summary_lines(by_id[node_id]))
        sys.stdout.write(renderer.next_row(node_id, edges, "○", text))


def _elided_count(estimate) -> str | None:
    """`(lower, upper)` as jj words it: a number, `N+`, or `some`."""
    lower, upper = estimate
    if lower == 0 and upper == 0:
        return None
    if lower == 0:
        return "some"
    if upper == lower:
        return str(lower)
    return f"{lower}+"


def print_operation_diff(args, settings, repo, from_ops, to_op,
                         *, heading: bool = True) -> int:
    """What changed between `from_ops` and `to_op`.

    `op diff` leads with the two operation summaries; `op show` has
    already printed the operation, so it asks for the body alone.
    """
    try:
        # A merge operation has several parents. They fold into one
        # operation before a repo view can be loaded from them.
        merged_from_op = repo.merge_operations(from_ops)
        from_repo = repo.load_at_operation(merged_from_op)
        to_repo = repo.load_at_operation(to_op)
        result = to_repo.operation_diff(
            from_repo, settings, getattr(args, "show_changes_in", None)
        )
    except (pyjj.JjError, pyjj.RepoLoadError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    if heading:
        for op in from_ops:
            print(f"From operation: {_op_summary(op)}")
        print(f"  To operation: {_op_summary(to_op)}")

    if result.changes or any(
        _elided_count(e) for e in
        (result.elided_newly_visible, result.elided_newly_hidden)
    ):
        print()
        print("Changed commits:")
        _print_changed_commits(repo, settings, result.changes,
                               getattr(args, "no_graph", False))
        parts = [
            f"{count} newly {label}"
            for count, label in (
                (_elided_count(result.elided_newly_visible), "added"),
                (_elided_count(result.elided_newly_hidden), "removed"),
            )
            if count
        ]
        if parts:
            print(f"   (Elided {' and '.join(parts)} revisions)")

    for change in result.changed_working_copies:
        print()
        print(f"Changed working copy {change.name}@:")
        _print_target(repo, settings, change.after, True)
        _print_target(repo, settings, change.before, False)

    _print_ref_section(repo, settings, "Changed local bookmarks:",
                       result.changed_local_bookmarks)
    _print_ref_section(repo, settings, "Changed local tags:",
                       result.changed_local_tags)
    _print_ref_section(repo, settings, "Changed remote bookmarks:",
                       result.changed_remote_bookmarks)
    _print_ref_section(repo, settings, "Changed remote tags:",
                       result.changed_remote_tags)
    return 0


def op_diff(args) -> int:
    try:
        settings, _ws, repo = _load(args)

        from_arg = getattr(args, "from_", None)
        to_arg = getattr(args, "to", None)
        if from_arg is not None or to_arg is not None:
            from_ops = [_resolve_operation(repo, from_arg or "@")]
            to_op = _resolve_operation(repo, to_arg or "@")
        else:
            to_op = _resolve_operation(repo, getattr(args, "operation", None))
            from_ops = to_op.parents()
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    return print_operation_diff(args, settings, repo, from_ops, to_op)
