use pyo3::prelude::*;
use pyo3::types::PyDict;

use jj_lib::gitignore::GitIgnoreFile;
use jj_lib::matchers::{EverythingMatcher, NothingMatcher};
use jj_lib::merge::Merge;
use jj_lib::merged_tree_builder::MergedTreeBuilder;
use jj_lib::repo_path::RepoPathBuf;
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::settings::HumanByteSize;
use jj_lib::transaction::Transaction;
use jj_lib::working_copy::SnapshotOptions;
use jj_lib::workspace::Workspace;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_backend_err, map_checkout_err, map_transaction_err, map_working_copy_err};
use crate::settings::PyUserSettings;
use crate::workspace::wrap_repo;

/// Reads `snapshot.max-new-file-size` the same way `cli`'s own
/// `WorkspaceCommandHelper::snapshot_options` does (including its `0` ->
/// "unlimited" convention) -- falls back to jj_lib's/`cli`'s own bundled
/// default (`"1MiB"`, in `cli/src/config/misc.toml`) if `settings` didn't
/// load that config layer (e.g. `UserSettings(load_config=False)`).
fn max_new_file_size(settings: &PyUserSettings) -> u64 {
    let HumanByteSize(size) = settings
        .0
        .get_value_with("snapshot.max-new-file-size", TryInto::try_into)
        .unwrap_or(HumanByteSize(1024 * 1024));
    if size == 0 { u64::MAX } else { size }
}

/// `jj status`/`jj diff`'s implicit "snapshot the working copy" step, as a
/// standalone operation: reads the current state of files on disk, updates
/// the workspace's working-copy commit to match (rewriting its tree; all
/// other fields like description/author are preserved), and commits that as
/// a new operation.
///
/// Per-directory `.gitignore` files are discovered and respected while
/// walking the working copy, same as `jj status`/`jj diff` (this is
/// `LocalWorkingCopy::snapshot()`'s own behavior, not something pyjj
/// implements). Not yet wired up: `.git/info/exclude` and the user's
/// global `core.excludesFile` (jj_lib's `SnapshotOptions::base_ignores`
/// parameter, left at `GitIgnoreFile::empty()` here) — these apply
/// repo-wide rather than being discovered from the tree, and reading them
/// needs the underlying git config, not just a repo-relative walk. All
/// non-ignored new files are auto-tracked (no `snapshot.auto-track`
/// pattern support yet, matching jj's own default of `"all()"`).
/// `snapshot.max-new-file-size` *is* honored (via `settings`), same as the
/// CLI's own `0` -> "unlimited" convention.
pub fn snapshot(
    workspace: &mut Workspace,
    settings: &PyUserSettings,
) -> PyResult<(PyReadonlyRepo, Py<PyAny>)> {
    let workspace_name = workspace.workspace_name().to_owned();
    let repo = pollster::block_on(workspace.repo_loader().load_at_head())
        .map_err(|err| crate::errors::RepoLoadError::new_err(err.to_string()))?;

    let wc_commit_id = repo
        .view()
        .get_wc_commit_id(&workspace_name)
        .cloned()
        .ok_or_else(|| {
            crate::errors::WorkingCopyError::new_err(format!(
                "Workspace `{}` has no working-copy commit",
                workspace_name.as_symbol()
            ))
        })?;
    let old_commit = pollster::block_on(repo.store().get_commit_async(&wc_commit_id))
        .map_err(map_backend_err)?;

    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;

    let options = SnapshotOptions {
        base_ignores: GitIgnoreFile::empty(),
        progress: None,
        start_tracking_matcher: &EverythingMatcher,
        force_tracking_matcher: &NothingMatcher,
        max_new_file_size: max_new_file_size(settings),
    };
    let (new_tree, stats) = pollster::block_on(locked_ws.locked_wc().snapshot(&options))
        .map_err(map_working_copy_err)?;

    // Nothing changed on disk: don't rewrite the wc commit (which would
    // bump its committer timestamp and commit id for no reason) or create
    // an empty operation — just release the working-copy lock as-is.
    if new_tree.tree_ids_and_labels() == old_commit.tree().tree_ids_and_labels() {
        pollster::block_on(locked_ws.finish(repo.operation().id().clone()))
            .map_err(map_working_copy_err)?;
        let py_repo = wrap_repo(workspace, repo);
        let stats_dict = Python::attach(|py| -> PyResult<Py<PyAny>> {
            let dict = PyDict::new(py);
            dict.set_item("untracked_paths", stats.untracked_paths.len())?;
            dict.set_item("changed", false)?;
            Ok(dict.unbind().into_any())
        })?;
        return Ok((py_repo, stats_dict));
    }

    let index = repo.readonly_index();
    let view = repo.view();
    let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
    let commit_builder = mut_repo.rewrite_commit(&old_commit).set_tree(new_tree);
    let new_commit = pollster::block_on(commit_builder.write()).map_err(map_backend_err)?;
    mut_repo
        .set_wc_commit(workspace_name.clone(), new_commit.id().clone())
        .map_err(|err| crate::errors::TransactionError::new_err(err.to_string()))?;
    // Required even though the wc commit has no descendants to rebase here:
    // any pending rewrite record must be cleared before `Transaction::commit`,
    // which asserts as much (`transaction.rs`, "Descendants have not been
    // rebased after the last rewrites").
    pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;

    let tx = Transaction::new(mut_repo, &settings.0);
    let new_repo =
        pollster::block_on(tx.commit("snapshot working copy")).map_err(map_transaction_err)?;

    pollster::block_on(locked_ws.finish(new_repo.operation().id().clone()))
        .map_err(map_working_copy_err)?;

    let py_repo = wrap_repo(workspace, new_repo);
    let stats_dict = Python::attach(|py| -> PyResult<Py<PyAny>> {
        let dict = PyDict::new(py);
        dict.set_item("untracked_paths", stats.untracked_paths.len())?;
        // `jj util snapshot` reports exactly this: whether the walk found
        // anything, which is the difference between "Snapshot complete."
        // and "No snapshot needed."
        dict.set_item("changed", true)?;
        Ok(dict.unbind().into_any())
    })?;
    Ok((py_repo, stats_dict))
}

/// `jj file untrack <paths>`, as one atomic operation.
///
/// The check jj makes cannot be done up front: whether a path stays gone
/// depends on the ignore rules the snapshot walk discovers, so jj removes
/// the paths, resets the working copy, snapshots again, and looks at what
/// came back. If anything did, nothing is persisted -- the transaction is
/// never committed and the working-copy lock is released unfinished, so
/// the repository is exactly as it was. That is why this lives in one
/// function instead of being driven from Python: the abort has to happen
/// before either half is written.
///
/// Returns the repository and the paths that came back. A non-empty list
/// means nothing was written.
pub fn untrack_paths(
    workspace: &mut Workspace,
    settings: &PyUserSettings,
    paths: Vec<String>,
) -> PyResult<(PyReadonlyRepo, Vec<String>)> {
    let workspace_name = workspace.workspace_name().to_owned();
    let repo = pollster::block_on(workspace.repo_loader().load_at_head())
        .map_err(|err| crate::errors::RepoLoadError::new_err(err.to_string()))?;
    let wc_commit_id = repo
        .view()
        .get_wc_commit_id(&workspace_name)
        .cloned()
        .ok_or_else(|| {
            crate::errors::WorkingCopyError::new_err(format!(
                "Workspace `{}` has no working-copy commit",
                workspace_name.as_symbol()
            ))
        })?;
    let old_commit = pollster::block_on(repo.store().get_commit_async(&wc_commit_id))
        .map_err(map_backend_err)?;

    let repo_paths = paths
        .iter()
        .map(|path| {
            RepoPathBuf::from_internal_string(path)
                .map_err(|err| crate::errors::JjError::new_err(err.to_string()))
        })
        .collect::<PyResult<Vec<_>>>()?;

    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;

    let mut builder = MergedTreeBuilder::new(old_commit.tree());
    for repo_path in &repo_paths {
        builder.set_or_remove(repo_path.clone(), Merge::absent());
    }
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;

    let index = repo.readonly_index();
    let view = repo.view();
    let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
    let commit_builder = mut_repo.rewrite_commit(&old_commit).set_tree(new_tree);
    let new_commit = pollster::block_on(commit_builder.write()).map_err(map_backend_err)?;
    mut_repo
        .set_wc_commit(workspace_name.clone(), new_commit.id().clone())
        .map_err(|err| crate::errors::TransactionError::new_err(err.to_string()))?;
    pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;

    pollster::block_on(locked_ws.locked_wc().reset(&new_commit)).map_err(map_working_copy_err)?;

    let options = SnapshotOptions {
        base_ignores: GitIgnoreFile::empty(),
        progress: None,
        start_tracking_matcher: &EverythingMatcher,
        force_tracking_matcher: &NothingMatcher,
        max_new_file_size: max_new_file_size(settings),
    };
    let (snapshot_tree, _stats) = pollster::block_on(locked_ws.locked_wc().snapshot(&options))
        .map_err(map_working_copy_err)?;

    let mut added_back = Vec::new();
    for (path, repo_path) in paths.iter().zip(&repo_paths) {
        let value = pollster::block_on(snapshot_tree.path_value(repo_path))
            .map_err(map_backend_err)?;
        if !value.is_absent() {
            added_back.push(path.clone());
        }
    }
    if !added_back.is_empty() {
        // Drop the lock without finishing: the reset and the rewritten
        // commit are never referenced by any operation.
        drop(locked_ws);
        let py_repo = wrap_repo(workspace, repo);
        return Ok((py_repo, added_back));
    }

    let tx = Transaction::new(mut_repo, &settings.0);
    let new_repo = pollster::block_on(tx.commit("untrack paths")).map_err(map_transaction_err)?;
    pollster::block_on(locked_ws.finish(new_repo.operation().id().clone()))
        .map_err(map_working_copy_err)?;

    let py_repo = wrap_repo(workspace, new_repo);
    Ok((py_repo, Vec::new()))
}

/// `jj new`/`jj edit`'s "update the physical working copy" step: writes
/// `commit`'s tree out to the working-copy files, and records `repo`'s
/// operation as the workspace's current operation.
///
/// Does not check whether the working copy changed on disk since it was
/// last read (i.e. always overwrites local edits with `commit`'s content) —
/// callers that need that safety check should snapshot first and compare.
pub fn check_out(
    workspace: &mut Workspace,
    repo: &PyReadonlyRepo,
    commit: &PyCommit,
) -> PyResult<Py<PyAny>> {
    let operation_id = repo.inner.operation().id().clone();
    let stats = pollster::block_on(workspace.check_out(operation_id, None, &commit.inner))
        .map_err(map_checkout_err)?;
    Python::attach(|py| -> PyResult<Py<PyAny>> {
        let dict = PyDict::new(py);
        dict.set_item("updated_files", stats.updated_files)?;
        dict.set_item("added_files", stats.added_files)?;
        dict.set_item("removed_files", stats.removed_files)?;
        dict.set_item("skipped_files", stats.skipped_files)?;
        Ok(dict.unbind().into_any())
    })
}

/// Re-syncs the working copy's *tracked-file-state bookkeeping* (recorded
/// mtimes/hashes) to `commit`'s tree, without touching a single file on
/// disk — distinct from `check_out()`, which unconditionally rewrites
/// files. For when something outside jj already made the working copy's
/// files match `commit` (the CLI's own use case, in
/// `WorkspaceCommandHelper::import_git_head`: a colocated repo's `git`
/// command moved Git HEAD and updated the files directly, so jj only needs
/// to stop considering its recorded state stale). Callers are responsible
/// for actually pointing the view's working-copy commit at `commit`
/// themselves first (e.g. via `Transaction.edit()`/`.set_wc_commit()`) —
/// this call only touches workspace-local tracked-file state, not the repo
/// view.
pub fn reset(workspace: &mut Workspace, repo: &PyReadonlyRepo, commit: &PyCommit) -> PyResult<()> {
    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;
    pollster::block_on(locked_ws.locked_wc().reset(&commit.inner)).map_err(map_working_copy_err)?;
    pollster::block_on(locked_ws.finish(repo.inner.operation().id().clone()))
        .map_err(map_working_copy_err)
}
