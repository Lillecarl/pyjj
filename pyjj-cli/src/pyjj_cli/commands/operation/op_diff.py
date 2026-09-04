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

from ...formatter import render_block, separate
from ..common import (
    CommandError,
    _bookmarks_by_commit,
    _commit_summary_spans,
    _format_timestamp,
    _formatter,
    _load,
    _resolve_operation,
    use_color,
)


def _op_summary_spans(op, prefix: str):
    """jj's `templates.op_summary`, in labelled pieces.

    The id, when the operation ended, and what it did. The root
    operation says `root()` where a time would go.
    """
    base = f"{prefix} operation"
    id_short = [(op.id[:12], f"{base} id short")]
    if not op.parent_ids:
        return separate([id_short, [("root()", f"{base} root")]], labels=base)
    when = [("(", base),
            (_format_timestamp(op.end_time), f"{base} time end local format"),
            (")", base)]
    first_line = op.description.splitlines()[0] if op.description else ""
    return separate(
        [id_short, when, [(first_line, f"{base} description first_line")]],
        labels=base,
    )


def _summary_spans(repo, settings, commit, wc_id, prefix: str):
    """A commit as `op diff` prints it, bookmarks and all.

    jj renders these with its `commit_summary` template, which names the
    bookmarks on a commit -- `movruppx 1a949896 main | one`. Dropping
    them would lose the one part of the line that says which branch an
    operation moved.

    The template labels the whole summary `working_copy` when the
    commit is the one the workspace sits on, which is why `wc_id` comes
    down here rather than being read off the repository: `op diff`
    asks against the repository at the newer operation, not the one
    the command is running at.
    """
    base = f"{prefix} commit"
    if wc_id is not None and commit.id.hex() == wc_id:
        base += " working_copy"
    bookmarks = _bookmarks_by_commit(repo).get(commit.id.hex(), [])
    return [(text, f"{base} {labels}".strip()) for text, labels
            in _commit_summary_spans(repo, settings, commit, bookmarks)]


def _target_lines(repo, settings, summary, added: bool, wc_id, prefix: str):
    """One side of a changed ref, `+` for the new state, `-` for the old.

    The sign is labelled `diff added` or `diff removed` on its own,
    outside the command's label, which is how jj writes it.
    """
    sign = [("+" if added else "-", "diff added" if added else "diff removed"),
            (" ", "")]
    state = [(f"{summary.state} ", "")] if summary.state else []

    def head(marker: str = ""):
        return sign + state + ([(marker, "")] if marker else [])

    if summary.absent:
        return [head() + [("(absent)", "")]]
    if summary.conflict:
        return (
            [head("(added) ")
             + _summary_spans(repo, settings, commit, wc_id, prefix)
             for commit in summary.commits]
            + [head("(removed) ")
               + _summary_spans(repo, settings, commit, wc_id, prefix)
               for commit in summary.removed_commits]
        )
    return [head() + _summary_spans(repo, settings, commit, wc_id, prefix)
            for commit in summary.commits]


def _write_lines(fmt, lines) -> None:
    """Each line's spans, then the newline jj writes under no labels."""
    for line in lines:
        for text, labels in line:
            fmt.write(text, *labels.split())
        fmt.write("\n")


def _ref_section(fmt, repo, settings, heading: str, changes, wc_id,
                 prefix: str) -> None:
    if not changes:
        return
    fmt.write("\n")
    fmt.write(f"{heading}\n")
    for change in changes:
        name = change.name
        if change.remote:
            name = f"{name}@{change.remote}"
        fmt.write(f"{name}:\n")
        _write_lines(fmt, _target_lines(repo, settings, change.after, True,
                                        wc_id, prefix))
        _write_lines(fmt, _target_lines(repo, settings, change.before, False,
                                        wc_id, prefix))


def _change_key(change):
    """The commit id jj keys a modified change by.

    A change that still exists is keyed by its new commit; one that was
    abandoned is keyed by the commit that went away.
    """
    commits = change.added or change.removed
    return commits[0].id


def _changed_commits(fmt, repo, settings, changes, no_graph: bool, wc_id,
                     prefix: str, coloured: bool) -> None:
    """The `Changed commits:` block, with or without its graph."""
    def summary_lines(change):
        sign = lambda added: [("+" if added else "-",
                               "diff added" if added else "diff removed"),
                              (" ", "")]
        return (
            [sign(True) + _summary_spans(repo, settings, commit, wc_id, prefix)
             for commit in change.added]
            + [sign(False)
               + _summary_spans(repo, settings, commit, wc_id, prefix)
               for commit in change.removed]
        )

    if no_graph:
        for change in changes:
            _write_lines(fmt, summary_lines(change))
        return

    # The graph is over the changed commits alone, so its order is its
    # own -- topologically grouped -- rather than the flat order above.
    # renderdag takes a finished string, so each row renders into its
    # own buffer rather than through the stream above.
    by_id = {_change_key(change).hex(): change for change in changes}
    renderer = pyjj.GraphRenderer()
    for node in repo.commits_graph([_change_key(change) for change in changes]):
        node_id = node.commit.id.hex()
        edges = [(edge.target.hex(), edge.edge_type) for edge in node.edges]
        text = render_block(summary_lines(by_id[node_id]), (), coloured)
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


def print_operation_diff(args, settings, ws, repo, from_ops, to_op,
                         *, heading: bool = True,
                         prefix: str = "op_diff") -> int:
    """What changed between `from_ops` and `to_op`.

    `op diff` leads with the two operation summaries; `op show` has
    already printed the operation, so it asks for the body alone and
    passes its own label as `prefix`.
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

    # jj renders the summaries against the repository at the newer
    # operation, so that is the view that decides which commit is the
    # working copy.
    wc_id = to_repo.view().get(ws.workspace_name)
    coloured = use_color(settings)
    with _formatter(settings) as fmt:
        if heading:
            for op in from_ops:
                fmt.write("From operation: ")
                _write_lines(fmt, [_op_summary_spans(op, prefix)])
            fmt.write("  To operation: ")
            _write_lines(fmt, [_op_summary_spans(to_op, prefix)])

        if result.changes or any(
            _elided_count(e) for e in
            (result.elided_newly_visible, result.elided_newly_hidden)
        ):
            fmt.write("\n")
            fmt.write("Changed commits:\n")
            _changed_commits(fmt, repo, settings, result.changes,
                             getattr(args, "no_graph", False), wc_id, prefix,
                             coloured)
            parts = [
                f"{count} newly {label}"
                for count, label in (
                    (_elided_count(result.elided_newly_visible), "added"),
                    (_elided_count(result.elided_newly_hidden), "removed"),
                )
                if count
            ]
            if parts:
                fmt.write(f"   (Elided {' and '.join(parts)} revisions)\n")

        for change in result.changed_working_copies:
            fmt.write("\n")
            fmt.write("Changed working copy ")
            fmt.write(f"{change.name}@", "working_copies")
            fmt.write(":\n")
            _write_lines(fmt, _target_lines(repo, settings, change.after, True,
                                            wc_id, prefix))
            _write_lines(fmt, _target_lines(repo, settings, change.before,
                                            False, wc_id, prefix))

        _ref_section(fmt, repo, settings, "Changed local bookmarks:",
                     result.changed_local_bookmarks, wc_id, prefix)
        _ref_section(fmt, repo, settings, "Changed local tags:",
                     result.changed_local_tags, wc_id, prefix)
        _ref_section(fmt, repo, settings, "Changed remote bookmarks:",
                     result.changed_remote_bookmarks, wc_id, prefix)
        _ref_section(fmt, repo, settings, "Changed remote tags:",
                     result.changed_remote_tags, wc_id, prefix)
    return 0


def op_diff(args) -> int:
    try:
        settings, ws, repo = _load(args)

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

    return print_operation_diff(args, settings, ws, repo, from_ops, to_op)
