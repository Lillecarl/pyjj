"""resolve subcommand: diffedit."""
import subprocess
import sys

from ..common import (
    _check_rewritable,
    command,
    _finish,
    _resolve_one,
    _rev,
    _changed_files,
    _split_changed,
    _run_diff_tool,
    _selection_is_empty,
    write_tx,
)


@command
def diffedit(args) -> int:
    """`jj diffedit`: edit a revision's own changes, or the diff between
    two revisions. Either way the edit lands on the destination side."""
    try:
        with write_tx(args) as (settings, ws, repo, tx):
            if not args.tool:
                print("Error: no diff editor specified; pass --tool",
                      file=sys.stderr)
                return 2
            revision = getattr(args, "revision", None)
            if revision and (args.from_ or args.into):
                print("Error: --revision cannot be used with --from or --to",
                      file=sys.stderr)
                return 2

            if args.from_ or args.into:
                to_commit = _resolve_one(repo, settings, _rev(args, "into"))
                from_commit = _resolve_one(repo, settings, _rev(args, "from_"))
                before, after = _split_changed(
                    _changed_files(repo, settings, from_commit, to_commit))
            else:
                # `-r` edits the revision's own changes, which are its diff
                # against the merge of its parents.
                to_commit = _resolve_one(repo, settings, revision or "@")
                paths = [entry.path for entry in to_commit.diff_from_parents(repo)]
                before = to_commit.parent_contents(repo, paths)
                after = {p: (to_commit.read_file(p) if to_commit.file_exists(p)
                             else None) for p in paths}

            if not before and not after:
                print("No changes to edit.")
                return 0
            selections = _run_diff_tool(settings, args.tool, before, after)
            if _selection_is_empty(selections, after):
                print("Nothing changed.", file=sys.stderr)
                return 0

            _check_rewritable(tx, settings, [to_commit])
            edited = tx.edit_commit_tree(to_commit, selections).write(repo)
            if to_commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, edited.id)
            _finish(
                tx, f"edit commit {to_commit.id.hex()}", settings, ws, repo,
                restore_descendants=getattr(args, "restore_descendants", False),
            )
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0
