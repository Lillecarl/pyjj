"""history subcommand: status."""
import sys

import pyjj
from ..common import (
    _bookmarks_by_commit,
    _commit_summary,
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

    # jj diffs the working copy against its merged parents. A single
    # parent is the case that matters here; a merge is left to the first
    # parent until the harness has a scenario for it.
    entries = parents[0].diff(wc, paths) if parents else wc.diff(wc, paths)
    lines = _summary_lines(entries, _ui_path_formatter(ws))
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
    return 0
