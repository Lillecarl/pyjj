"""operation subcommand: op diff — what changed between two operations.

Mirrors `cli/src/commands/operation/diff.rs`. The whole comparison lives
in `ReadonlyRepo.operation_diff()`; this module only names the two
operations and prints the result.

The rendering is the flat one `jj op diff --no-graph` produces. The
graph and the `--patch` diff bodies are not drawn yet, so `--no-graph`
is accepted and ignored rather than refused.
"""
import sys

import pyjj

from ..common import CommandError, _load, _resolve_operation


def _commit_summary(commit) -> str:
    """One commit, in the shape `templates.commit_summary` renders."""
    description = (
        commit.description.splitlines()[0]
        if commit.description
        else "(no description set)"
    )
    return (
        f"{commit.change_id.reverse_hex()[:8]} "
        f"{commit.id.hex()[:8]} {description}"
    )


def _op_summary(op) -> str:
    return f"{op.id[:12]} {op.description}".rstrip()


def _print_target(summary, added: bool) -> None:
    """One side of a changed ref, `+` for the new state, `-` for the old."""
    sign = "+" if added else "-"
    prefix = f"{summary.state} " if summary.state else ""
    if summary.absent:
        print(f"{sign} {prefix}(absent)")
        return
    if summary.conflict:
        for commit in summary.commits:
            print(f"{sign} {prefix}(added) {_commit_summary(commit)}")
        for commit in summary.removed_commits:
            print(f"{sign} {prefix}(removed) {_commit_summary(commit)}")
        return
    for commit in summary.commits:
        print(f"{sign} {prefix}{_commit_summary(commit)}")


def _print_ref_section(heading: str, changes) -> None:
    if not changes:
        return
    print()
    print(heading)
    for change in changes:
        name = change.name
        if change.remote:
            name = f"{name}@{change.remote}"
        print(f"{name}:")
        _print_target(change.after, True)
        _print_target(change.before, False)


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

        # A merge operation has several parents. They fold into one
        # operation before a repo view can be loaded from them.
        merged_from_op = repo.merge_operations(from_ops)
        from_repo = repo.load_at_operation(merged_from_op)
        to_repo = repo.load_at_operation(to_op)
        result = to_repo.operation_diff(
            from_repo, settings, getattr(args, "show_changes_in", None)
        )
    except (pyjj.JjError, pyjj.WorkspaceLoadError, pyjj.RepoLoadError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    for op in from_ops:
        print(f"From operation: {_op_summary(op)}")
    print(f"  To operation: {_op_summary(to_op)}")

    if result.changes or any(
        _elided_count(e) for e in
        (result.elided_newly_visible, result.elided_newly_hidden)
    ):
        print()
        print("Changed commits:")
        for change in result.changes:
            for commit in change.added:
                print(f"+ {_commit_summary(commit)}")
            for commit in change.removed:
                print(f"- {_commit_summary(commit)}")
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
        _print_target(change.after, True)
        _print_target(change.before, False)

    _print_ref_section("Changed local bookmarks:", result.changed_local_bookmarks)
    _print_ref_section("Changed local tags:", result.changed_local_tags)
    _print_ref_section("Changed remote bookmarks:", result.changed_remote_bookmarks)
    _print_ref_section("Changed remote tags:", result.changed_remote_tags)
    return 0
