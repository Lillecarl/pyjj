"""history subcommand: status."""
import sys

import pyjj
from ..common import (
    _bookmarks_by_commit,
    _commit_summary,
    _conflict_lines,
    _load,
    _summary_lines,
    _ui_path_formatter,
    _wc_commit,
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
    lines = _summary_lines(entries, to_ui_path)
    if lines:
        print("Working copy changes:")
        for line in lines:
            print(line)
    else:
        print("The working copy has no changes.")

    bookmarks = _bookmarks_by_commit(repo)
    print(f"Working copy  (@) : "
          f"{_commit_summary(repo, settings, wc, bookmarks.get(wc.id.hex(), []))}")
    for parent in parents:
        print(f"Parent commit (@-): "
              f"{_commit_summary(repo, settings, parent, bookmarks.get(parent.id.hex(), []))}")

    conflicts = _conflict_lines(wc, to_ui_path) if wc.has_conflict else []
    if conflicts:
        print("Warning: There are unresolved conflicts at these paths:")
        for line in conflicts:
            print(line)
    return 0
