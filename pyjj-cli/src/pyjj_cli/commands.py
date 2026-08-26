"""CLI command implementations exercising pyjj bindings.

Command semantics mirror the real `jj` CLI (0.43-era): every
workspace-attached command implicitly snapshots the working copy before
acting, descriptions go through complete_newline, and `jj abandon`
deletes bookmarks on the abandoned commits unless told otherwise.
"""

import sys
from pathlib import Path

import pyjj


def complete_newline(s: str) -> str:
    """The real CLI's text_util::complete_newline: append exactly one
    trailing newline to non-empty text lacking one; empty stays empty.
    jj_lib stores descriptions verbatim, so this normalization lives at
    the frontend."""
    if s and not s.endswith("\n"):
        return s + "\n"
    return s


def join_message_paragraphs(paragraphs) -> str:
    """The real CLI's description_util::join_message_paragraphs: each -m
    becomes a paragraph completed with a newline, paragraphs separated by
    one blank line."""
    return "\n".join(complete_newline(p) for p in paragraphs)


class CommandError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _load(args):
    """Load settings + workspace at the -R path, snapshotting the working
    copy first like every real jj workspace command does."""
    settings = pyjj.UserSettings()
    ws = pyjj.Workspace.load(settings, args.repository)
    repo, _stats = ws.snapshot(settings)
    return settings, ws, repo


def _resolve_all(repo, settings, expressions):
    commits = []
    for expr in expressions:
        commits.extend(repo.revset(settings, expr))
    return commits


def _resolve_one(repo, settings, expression):
    matches = repo.revset(settings, expression)
    if len(matches) != 1:
        raise CommandError(f"revset `{expression}` resolved to {len(matches)} revisions")
    return matches[0]


def _wc_commit(repo, ws):
    return repo.get_commit(pyjj.CommitId(repo.view()[ws.workspace_name]))


def _checkout_if_moved(settings, ws, old_wc_hex) -> None:
    """Mirror the real CLI's transaction-finish behavior: when the current
    view's working-copy commit differs from `old_wc_hex`, update the
    on-disk working copy to match."""
    fresh_ws = pyjj.Workspace.load(settings, ws.workspace_root)
    fresh_repo = fresh_ws.load_at_head()
    new_wc_hex = fresh_repo.view()[fresh_ws.workspace_name]
    if new_wc_hex != old_wc_hex:
        fresh_ws.check_out(fresh_repo, fresh_repo.get_commit(pyjj.CommitId(new_wc_hex)))


def _finish(tx, description, settings, ws, base_repo, *, delete_abandoned_bookmarks=False):
    """Commit the transaction, then mirror the real CLI's
    transaction-finish behavior: when a rewrite moved the working-copy
    commit (e.g. an abandon or rebase rebased it), update the on-disk
    working copy to match."""
    old_wc_hex = base_repo.view()[ws.workspace_name]
    tx.rebase_descendants(delete_abandoned_bookmarks)
    tx.commit(description)
    _checkout_if_moved(settings, ws, old_wc_hex)


def _restore_view_command(tx, description, settings, ws, repo):
    """Shared tail for view-restoring operations (undo/redo/op restore):
    they produce no rewrites to rebase and take their operation description
    verbatim from the binding -- for undo/redo it encodes the target op so
    future stack jumps keep working."""
    old_wc_hex = repo.view()[ws.workspace_name]
    tx.commit(description)
    _checkout_if_moved(settings, ws, old_wc_hex)


# -- commands --------------------------------------------------------------


def git_init(args) -> int:
    """`jj git init` — create a new jj repo backed by an internal Git store."""
    settings = pyjj.UserSettings()
    # Real `jj git init` creates missing parent directories.
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        ws, repo = pyjj.Workspace.init_internal_git(settings, str(destination))
    except pyjj.WorkspaceInitError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Initialized repo in {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0


def status(args) -> int:
    try:
        _settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Workspace: {ws.workspace_root}")
    view = repo.view()
    for ws_name, commit_id in view.items():
        commit = repo.get_commit(pyjj.CommitId(commit_id))
        desc = commit.description.splitlines()[0] if commit.description else "(no description set)"
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]} {desc}")
    return 0


def log(args) -> int:
    try:
        _settings, _ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    view = repo.view()
    seen = set()
    queue: list = [(cid, 0) for cid in view.values()]

    while queue and args.limit > 0:
        commit_id_hex, indent = queue.pop(0)
        if commit_id_hex in seen:
            continue
        seen.add(commit_id_hex)

        commit = repo.get_commit(pyjj.CommitId(commit_id_hex))
        prefix = "  " * indent
        desc = commit.description.splitlines()[0] if commit.description else "(no description)"
        print(f"{prefix}@ {commit_id_hex[:12]} {desc}")

        args.limit -= 1
        if indent < 5:
            for parent_id in commit.parent_ids:
                queue.append((parent_id.hex(), indent + 1))

    return 0


def describe(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    if args.stdin:
        description = sys.stdin.read()
    elif args.messages:
        description = join_message_paragraphs(args.messages)
    else:
        print("Error: interactive description editing is not supported; "
              "pass -m or --stdin", file=sys.stderr)
        return 2

    revsets = list(args.revisions_pos or [])
    if args.revisions_opt:
        revsets.extend(args.revisions_opt)
    if not revsets:
        revsets = ["@"]

    try:
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to describe.")
            return 0

        tx = repo.start_transaction(settings)
        new_wc_id = None
        wc_id = repo.view().get(ws.workspace_name)
        for commit in targets:
            builder = (
                tx.rewrite_commit(settings, commit)
                .set_description(description)
            )
            new_commit = builder.write(repo)
            if commit.id.hex() == wc_id:
                new_wc_id = new_commit.id
        if new_wc_id is not None:
            tx.set_wc_commit(ws.workspace_name, new_wc_id)
        _finish(tx, f"describe commit {targets[0].id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def new(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        if args.parents_pos:
            parents = _resolve_all(repo, settings, args.parents_pos)
        else:
            parents = [_wc_commit(repo, ws)]
        tx = repo.start_transaction(settings)
        builder = tx.new_commit(settings, [c.id for c in parents])
        if args.message:
            builder = builder.set_description(complete_newline(args.message))
        child = builder.write(repo)
        tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, "new empty commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def bookmark(args) -> int:
    """`jj bookmark create NAMES... [-r REVSET]` / `bookmark set NAME -r REVSET`."""
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision)
        tx = repo.start_transaction(settings)
        if hasattr(args, "names"):
            for name in args.names:
                if repo.get_bookmark(name) is not None:
                    raise CommandError(
                        f"Bookmark already exists: {name} "
                        "(use `bookmark set` to move it)"
                    )
                tx.set_bookmark(name, target.id)
        else:
            if repo.get_bookmark(args.name) is None:
                raise CommandError(f"No such bookmark: {args.name}")
            tx.set_bookmark(args.name, target.id)
        _finish(tx, f"point bookmark at {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def squash(args) -> int:
    try:
        settings, ws, repo = _load(args)
        sources = _resolve_all(repo, settings, list(args.from_ or []) + list(args.revision or []))
        if not sources:
            sources = [_wc_commit(repo, ws)]
        if len(sources) != 1:
            raise CommandError("squashing multiple source revisions is not supported yet")
        source = sources[0]
        dest = (
            _resolve_one(repo, settings, args.into)
            if args.into
            else repo.get_commit(source.parent_ids[0])
        )

        # Message handling, mirroring the real CLI's non-interactive paths.
        # -u keeps the destination's description untouched; -m replaces;
        # with no flag, a single non-empty side wins and two non-empty
        # descriptions need the user (interactive editing is unsupported).
        use_dest_desc = args.use_destination_message and args.message is None
        if args.message is not None:
            description = complete_newline(args.message)
        else:
            candidates = [c.description for c in [source, dest] if c.description]
            if len(candidates) == 1:
                description = candidates[0]
            elif len(candidates) == 0:
                description = ""
            elif not args.use_destination_message:
                raise CommandError(
                    "both source and destination have descriptions; "
                    "pass -m or --use-destination-message"
                )

        tx = repo.start_transaction(settings)
        builder = tx.squash(source, dest)
        if builder is None:
            print("Nothing changed.")
            return 0
        if not use_dest_desc:
            builder = builder.set_description(description)
        builder.write(repo)
        _finish(tx, "squash commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def rebase(args) -> int:
    try:
        settings, ws, repo = _load(args)
        if not args.revisions:
            print("Error: currently only `-r REVSETS` mode is supported", file=sys.stderr)
            return 2
        targets = _resolve_all(repo, settings, args.revisions)
        destinations = _resolve_all(repo, settings, args.destinations)
        tx = repo.start_transaction(settings)
        tx.move_commits([c.id for c in targets], [], [d.id for d in destinations], [])
        _finish(tx, "rebase commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def abandon(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revsets = args.revisions_pos or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to abandon.")
            return 0
        tx = repo.start_transaction(settings)
        for commit in targets:
            tx.abandon_commit(commit)
        # The real `jj abandon` deletes bookmarks pointing at the abandoned
        # commits by default (--retain-bookmarks moves them instead).
        _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws, repo,
                delete_abandoned_bookmarks=True)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def duplicate(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revsets = args.revisions_pos or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        tx = repo.start_transaction(settings)
        tx.duplicate(targets)
        _finish(tx, "duplicate commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def edit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision_pos)
        tx = repo.start_transaction(settings)
        # MutableRepo::edit abandons a discardable, unreferenced old wc
        # itself; rebase_descendants() in _finish clears the pending map.
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"edit commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def commit(args) -> int:
    """`jj commit`: describe @, then put the selected paths (or all of @'s
    change) into it and create a new working-copy child on top."""
    try:
        settings, ws, repo = _load(args)
        if args.interactive or args.tool or args.editor:
            print("Error: interactive commit is not supported; pass -m "
                  "(with optional FILESETS)", file=sys.stderr)
            return 2
        if args.message is None:
            print("Error: interactive description editing is not supported; "
                  "pass -m", file=sys.stderr)
            return 2

        wc = _wc_commit(repo, ws)
        tx = repo.start_transaction(settings)
        if args.paths_pos:
            # Selected paths stay in @ (same change id); everything else
            # moves to the new child -- the same primitives `split` uses,
            # with the roles reversed.
            kept = (
                tx.split_selected(wc, list(args.paths_pos))
                .set_description(complete_newline(args.message))
                .write(repo)
            )
            child = tx.split_remainder(wc, kept).write(repo)
        else:
            described = (
                tx.rewrite_commit(settings, wc)
                .set_description(complete_newline(args.message))
                .write(repo)
            )
            child = tx.new_commit(settings, [described.id]).write(repo)
        tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, f"commit {wc.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def restore(args) -> int:
    try:
        settings, ws, repo = _load(args)
        src = _resolve_one(repo, settings, args.from_)
        dst = _resolve_one(repo, settings, args.into)
        paths = list(args.paths_pos) or None
        tx = repo.start_transaction(settings)
        builder = tx.restore(src, dst, paths)
        restored = builder.write(repo)
        if dst.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, restored.id)
        _finish(tx, f"restore from {src.id.hex()} into {dst.id.hex()}",
                settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def split(args) -> int:
    try:
        settings, ws, repo = _load(args)
        if not args.paths_pos:
            print("Error: interactive split is not supported; pass FILESETS",
                  file=sys.stderr)
            return 2
        if args.message is None:
            print("Error: interactive description editing is not supported; "
                  "pass -m for the first half's description", file=sys.stderr)
            return 2
        target = _resolve_one(repo, settings, args.revision or "@")

        tx = repo.start_transaction(settings)
        first_builder = tx.split_selected(target, list(args.paths_pos))
        first = first_builder.set_description(complete_newline(args.message)).write(repo)
        second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def undo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _undone, _restored_to, description = tx.undo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def redo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _redone, _restored_to, description = tx.redo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def op_restore(args) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    try:
        settings, ws, repo = _load(args)
        target = repo.load_operation(args.operation_pos)
        tx = repo.start_transaction(settings)
        tx.restore_operation(target)
        _restore_view_command(
            tx, f"restore operation {args.operation_pos}", settings, ws, repo
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def version(args) -> int:
    print(f"pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
