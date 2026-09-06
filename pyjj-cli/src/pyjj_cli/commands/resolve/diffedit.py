"""resolve subcommand: diffedit."""
import subprocess
import sys

import pyjj
from ..common import (
    _start_transaction,
    _check_rewritable,
    CommandError,
    _finish,
    _load,
    _resolve_one,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
)


def diffedit(args) -> int:
    """`jj diffedit`: edit a revision's own changes, or the diff between
    two revisions. Either way the edit lands on the destination side."""
    try:
        settings, ws, repo = _load(args)
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
            to_commit = _resolve_one(repo, settings, args.into or "@")
            from_commit = _resolve_one(repo, settings, args.from_ or "@")
            changed = _changed_files(repo, settings, from_commit, to_commit)
            before = {p: b for p, (b, _a) in changed.items()}
            after = {p: a for p, (_b, a) in changed.items()}
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
            print("Nothing changed.")
            return 0

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, [to_commit])
        edited = tx.edit_commit_tree(to_commit, selections).write(repo)
        if to_commit.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, edited.id)
        _finish(
            tx, f"edit commit {to_commit.id.hex()}", settings, ws, repo,
            restore_descendants=getattr(args, "restore_descendants", False),
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0
