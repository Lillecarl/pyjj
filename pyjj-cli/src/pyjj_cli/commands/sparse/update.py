"""The shared tail of `sparse set`, `reset` and `edit`."""
import sys


def update_sparse_patterns(ws, repo, patterns) -> None:
    """jj's `update_sparse_patterns_with`: deduplicate and sort, set the
    patterns, then report the checkout like `print_checkout_stats`.

    jj sorts `RepoPathBuf`s by component, so `a/b` sorts before `a-b`
    although `/` is the larger byte.
    """
    ordered = sorted(set(patterns), key=lambda p: p.split("/") if p else [])
    stats = ws.set_sparse_patterns(ordered)
    if stats["added_files"] or stats["updated_files"] or stats["removed_files"]:
        print(f"Added {stats['added_files']} files, modified "
              f"{stats['updated_files']} files, removed "
              f"{stats['removed_files']} files", file=sys.stderr)
    if stats["skipped_files"]:
        short = repo.view()[ws.workspace_name][:12]
        print(f"Warning: {stats['skipped_files']} of those updates were "
              f"skipped because there were conflicting changes in the "
              f"working copy.", file=sys.stderr)
        print(f"Hint: Inspect the changes compared to the intended target "
              f"with `jj diff --from {short}`.\n"
              f"Discard the conflicting changes with "
              f"`jj restore --from {short}`.", file=sys.stderr)
