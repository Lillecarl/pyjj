"""Mutating actions, one function per action.

Each function has the shape `(workspace, repo, settings, ...) -> ReadonlyRepo`
expected by `AppState.run_mutation()` (see `state.py`): it creates a
`Transaction`, mutates it, and commits it, all synchronously and all on the
one thread `run_mutation()` runs it on. `Transaction`/`CommitBuilder` are
`unsendable` on the Rust side, so none of this may be split across an
`await` boundary or handed to another thread mid-transaction -- see
`AGENTS.md`'s "the one load-bearing async rule".
"""

import pyjj


def _sync_working_copy(
    workspace: pyjj.Workspace, repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings
) -> None:
    """`Transaction.edit()`/`set_wc_commit()` only update the repo's *view*
    of which commit is checked out; the on-disk files need a separate
    `Workspace.check_out()` call to actually catch up.
    """
    workspace.check_out(repo, repo.resolve_single(settings, "@"))


def new_child(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    parents: list[pyjj.Commit],
) -> pyjj.ReadonlyRepo:
    """`jj new <parent>...` equivalent: create and check out a new child
    commit. Two or more parents makes it a merge commit -- LogView.selection
    is how the UI feeds multiple marked commits in here at once.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [p.id for p in parents])
    child = builder.write(repo)
    tx.edit(workspace.workspace_name, child)
    tx.rebase_descendants()
    message = "new merge commit" if len(parents) > 1 else "new empty commit"
    new_repo = tx.commit(message)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def edit(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    commit: pyjj.Commit,
) -> pyjj.ReadonlyRepo:
    """`jj edit <commit>` equivalent: check out an existing commit directly."""
    tx = repo.start_transaction(settings)
    tx.edit(workspace.workspace_name, commit)
    tx.rebase_descendants()
    new_repo = tx.commit(f"edit commit {commit.change_id.hex()[:8]}")
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def describe(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    commit: pyjj.Commit,
    text: str,
) -> pyjj.ReadonlyRepo:
    """`jj describe <commit>` equivalent: rewrite a commit's description."""
    was_wc = commit.id == repo.resolve_single(settings, "@").id
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, commit)
    builder.set_description(text)
    new_commit = builder.write(repo)
    if was_wc:
        tx.set_wc_commit(workspace.workspace_name, new_commit.id)
    tx.rebase_descendants()
    new_repo = tx.commit(f"describe commit {commit.change_id.hex()[:8]}")
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def abandon(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    commits: list[pyjj.Commit],
) -> pyjj.ReadonlyRepo:
    """`jj abandon <commit>...` equivalent -- one transaction for the whole
    batch, not one per commit, so it's a single undo-able operation.
    """
    tx = repo.start_transaction(settings)
    for commit in commits:
        tx.abandon_commit(commit)
    tx.rebase_descendants()
    if len(commits) > 1:
        message = f"abandon {len(commits)} commits"
    else:
        message = f"abandon commit {commits[0].change_id.hex()[:8]}"
    new_repo = tx.commit(message)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def rebase(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    sources: list[pyjj.Commit],
    destination: pyjj.Commit,
    mode: str,
    include_descendants: bool,
) -> pyjj.ReadonlyRepo:
    """`jj rebase` equivalent covering every destination mode in one
    function: `mode="onto"` is `-d <destination>`, `"after"` is `-A
    <destination>` (splices in as a child of destination, taking over its
    current children), `"before"` is `-B <destination>` (splices in as a
    parent of destination, taking over its current parents).
    `include_descendants` selects `-s <sources[0]>` (source and everything
    below it) over the default `-r <sources...>` (just the named commits,
    reparenting their children onto the commits' own original parents) --
    only meaningful with exactly one source commit, same as `jj rebase -s`
    taking one source revision.

    Delegates the actual graph surgery to `Transaction.move_commits`
    (`jj_lib::rewrite::move_commits`), computing only which commits
    `-A`/`-B` implies as `new_child_ids` -- see `pyjj-bindings/src/rewrite.rs`'s
    `move_commits` docs for why that graph-surgery logic itself isn't
    reimplemented here.
    """
    tx = repo.start_transaction(settings)

    if include_descendants:
        target_commit_ids, target_root_ids = [], [sources[0].id]
    else:
        target_commit_ids, target_root_ids = [c.id for c in sources], []

    if mode == "onto":
        new_parent_ids, new_child_ids = [destination.id], []
    elif mode == "after":
        children = repo.revset(settings, f"children({destination.id.hex()})")
        new_parent_ids, new_child_ids = [destination.id], [c.id for c in children]
    elif mode == "before":
        new_parent_ids, new_child_ids = list(destination.parent_ids), [destination.id]
    else:
        raise ValueError(f"unknown rebase mode: {mode!r}")

    tx.move_commits(target_commit_ids, target_root_ids, new_parent_ids, new_child_ids)
    tx.rebase_descendants()

    if len(sources) > 1:
        subject = f"{len(sources)} commits"
    else:
        subject = f"commit {sources[0].change_id.hex()[:8]}"
        if include_descendants:
            subject += " and descendants"
    message = f"rebase {subject} {mode} {destination.change_id.hex()[:8]}"

    new_repo = tx.commit(message)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def squash(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    source: pyjj.Commit,
    use_destination_message: bool,
) -> pyjj.ReadonlyRepo:
    """`jj squash` equivalent: moves `source` into its own single parent,
    always -- squash is inherently one source into one destination, so
    unlike `new_child`/`abandon`/`rebase` this never takes a list. Raises
    for a merge-commit source since plain `jj squash` does not infer a
    destination among several parents either.
    """
    if len(source.parent_ids) != 1:
        raise pyjj.JjError(
            "squash needs an explicit destination for a merge commit (not supported here yet)"
        )
    destination = repo.get_commit(source.parent_ids[0])
    tx = repo.start_transaction(settings)
    builder = tx.squash(source, destination)
    if builder is None:
        return repo
    if use_destination_message:
        message = destination.description
    else:
        message = destination.description or source.description
    builder.set_description(message)
    builder.write(repo)
    tx.rebase_descendants()
    commit_message = f"squash {source.change_id.hex()[:8]} into {destination.change_id.hex()[:8]}"
    new_repo = tx.commit(commit_message)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def duplicate(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    commits: list[pyjj.Commit],
) -> pyjj.ReadonlyRepo:
    """`jj duplicate` equivalent: copies onto each commit's own original
    parents, leaving the originals (and the working copy) untouched --
    no `rebase_descendants()`/`_sync_working_copy()` needed.
    """
    tx = repo.start_transaction(settings)
    tx.duplicate(commits)
    if len(commits) > 1:
        message = f"duplicate {len(commits)} commits"
    else:
        message = f"duplicate commit {commits[0].change_id.hex()[:8]}"
    return tx.commit(message)


def restore_operation(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    target_op: pyjj.Operation,
) -> pyjj.ReadonlyRepo:
    """`jj op restore <target_op>` equivalent: makes the repo's view
    (bookmarks, heads, working copy, remote-tracking state) exactly
    `target_op`'s -- both portions, unlike `Transaction.restore_operation`'s
    `what` parameter which the op-log screen doesn't expose a way to
    split.
    """
    tx = repo.start_transaction(settings)
    tx.restore_operation(target_op)
    new_repo = tx.commit(f"restore to operation {target_op.id[:8]}")
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def set_bookmark(
    workspace: pyjj.Workspace,
    repo: pyjj.ReadonlyRepo,
    settings: pyjj.UserSettings,
    commit: pyjj.Commit,
    name: str,
) -> pyjj.ReadonlyRepo:
    """`jj bookmark set <name> -r <commit>` equivalent: point a (possibly
    new) local bookmark at `commit`. No working-copy sync needed -- this
    never touches the wc commit or registers a rewrite.
    """
    tx = repo.start_transaction(settings)
    tx.set_bookmark(name, commit.id)
    return tx.commit(f"set bookmark {name} to {commit.change_id.hex()[:8]}")


def undo(
    workspace: pyjj.Workspace, repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings
) -> pyjj.ReadonlyRepo:
    """`jj undo` equivalent."""
    tx = repo.start_transaction(settings)
    _undone_op, _restored_op, description = tx.undo()
    new_repo = tx.commit(description)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo


def redo(
    workspace: pyjj.Workspace, repo: pyjj.ReadonlyRepo, settings: pyjj.UserSettings
) -> pyjj.ReadonlyRepo:
    """`jj redo` equivalent, the complement of `undo()`."""
    tx = repo.start_transaction(settings)
    _undone_op, _restored_op, description = tx.redo()
    new_repo = tx.commit(description)
    _sync_working_copy(workspace, new_repo, settings)
    return new_repo
