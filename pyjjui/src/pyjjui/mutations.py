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
    parent: pyjj.Commit,
) -> pyjj.ReadonlyRepo:
    """`jj new <parent>` equivalent: create and check out a new child commit."""
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    child = builder.write(repo)
    tx.edit(workspace.workspace_name, child)
    tx.rebase_descendants()
    new_repo = tx.commit("new empty commit")
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
    commit: pyjj.Commit,
) -> pyjj.ReadonlyRepo:
    """`jj abandon <commit>` equivalent."""
    tx = repo.start_transaction(settings)
    tx.abandon_commit(commit)
    tx.rebase_descendants()
    new_repo = tx.commit(f"abandon commit {commit.change_id.hex()[:8]}")
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
