"""history subcommand: status."""
import sys

import pyjj
from ..common import (
    _bookmarks_by_commit,
    _commit_summary_spans,
    _conflict_spans,
    _formatter,
    _load,
    _summary_spans,
    _ui_path_formatter,
    _wc_commit,
    _write_lines,
)


def status(args) -> int:
    """`jj status` — the working copy, its parents, and what changed."""
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    paths = getattr(args, "filesets", None) or None
    wc = _wc_commit(repo, ws)
    parents = [repo.get_commit(pid) for pid in wc.parent_ids]

    # Against the parents *merged*, not the first one. A merge that
    # resolves nothing changes nothing, and diffing against one parent
    # would report everything the others contributed.
    to_ui_path = _ui_path_formatter(ws)
    entries = wc.diff_from_parents(repo, paths)
    bookmarks = _bookmarks_by_commit(repo)

    def summary(commit, working_copy: bool):
        """One commit, under the labels jj gives a bare summary."""
        base = "commit working_copy" if working_copy else "commit"
        return [(text, f"{base} {labels}".strip()) for text, labels
                in _commit_summary_spans(repo, settings, commit,
                                         bookmarks.get(commit.id.hex(), []))]

    with _formatter(settings) as fmt:
        changes = _summary_spans(entries, to_ui_path)
        if changes:
            fmt.write("Working copy changes:\n")
            _write_lines(fmt, changes, "diff summary")
        else:
            fmt.write("The working copy has no changes.\n")

        fmt.write("Working copy  (@) : ")
        _write_lines(fmt, [summary(wc, True)])
        for parent in parents:
            fmt.write("Parent commit (@-): ")
            _write_lines(fmt, [summary(parent, False)])

        conflicts = _conflict_spans(wc, to_ui_path) if wc.has_conflict else []
        if conflicts:
            # jj writes a warning's heading as its own span, so the word
            # `Warning:` is bright while the sentence is only bold.
            fmt.write("Warning: ", "warning", "heading")
            fmt.write("There are unresolved conflicts at these paths:",
                      "warning")
            fmt.sync()
            fmt.write("\n")
            _write_lines(fmt, conflicts)
    return 0
