use std::path::{Path, PathBuf};
use std::sync::Arc;

use pyo3::prelude::*;

use jj_lib::commit::Commit;
use jj_lib::config::ConfigGetError;
use jj_lib::fileset::{FilesetAliasesMap, FilesetDiagnostics, FilesetParseContext};
use jj_lib::gitignore::GitIgnoreFile;
use jj_lib::matchers::{Matcher, NothingMatcher};
use jj_lib::merge::Merge;
use jj_lib::merged_tree_builder::MergedTreeBuilder;
use jj_lib::op_store::OpStoreError;
use jj_lib::object_id::ObjectId as _;
use jj_lib::ref_name::WorkspaceName;
use jj_lib::repo::{ReadonlyRepo, Repo as _};
use jj_lib::repo_path::{RepoPath, RepoPathBuf};
use jj_lib::settings::HumanByteSize;
use jj_lib::store::Store;
use jj_lib::ui_path::RepoPathUiConverter;
use jj_lib::working_copy::{
    CheckoutStats, LockedWorkingCopy, SnapshotOptions, UntrackedReason, WorkingCopyFreshness,
};
use jj_lib::workspace::Workspace;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{
    WorkingCopyError, map_backend_err, map_checkout_err, map_transaction_err, map_working_copy_err,
};
use crate::settings::PyUserSettings;
use crate::workspace::wrap_repo;

/// What `jj`'s `snapshot_options_with_start_tracking_matcher` reads from
/// config and from Git, loaded once per snapshot.
///
/// A key `settings` did not load (`UserSettings(load_config=False)`)
/// falls back to jj's bundled default: `snapshot.auto-track = "all()"`
/// and `snapshot.max-new-file-size = "1MiB"`. A key that is set but
/// invalid raises.
pub(crate) struct SnapshotConfig {
    base_ignores: Arc<GitIgnoreFile>,
    auto_track: Box<dyn Matcher>,
    max_new_file_size: u64,
}

impl SnapshotConfig {
    pub(crate) fn load(
        settings: &PyUserSettings,
        workspace_root: &Path,
        store: &Store,
    ) -> PyResult<Self> {
        let HumanByteSize(size) = match settings
            .0
            .get_value_with("snapshot.max-new-file-size", TryInto::try_into)
        {
            Err(ConfigGetError::NotFound { .. }) => HumanByteSize(1024 * 1024),
            other => other.map_err(config_err)?,
        };
        Ok(Self {
            base_ignores: base_ignores(workspace_root, store)?,
            auto_track: auto_track_matcher(settings, workspace_root)?,
            max_new_file_size: if size == 0 { u64::MAX } else { size },
        })
    }

    pub(crate) fn options(&self) -> SnapshotOptions<'_> {
        SnapshotOptions {
            base_ignores: self.base_ignores.clone(),
            progress: None,
            start_tracking_matcher: self.auto_track.as_ref(),
            force_tracking_matcher: &NothingMatcher,
            max_new_file_size: self.max_new_file_size,
        }
    }
}

fn config_err(err: ConfigGetError) -> PyErr {
    crate::errors::JjError::new_err(err.to_string())
}

/// `snapshot.auto-track`, parsed as a fileset rooted at the workspace.
fn auto_track_matcher(settings: &PyUserSettings, workspace_root: &Path) -> PyResult<Box<dyn Matcher>> {
    let pattern = match settings.0.get_string("snapshot.auto-track") {
        Err(ConfigGetError::NotFound { .. }) => "all()".to_owned(),
        other => other.map_err(config_err)?,
    };
    let path_converter = RepoPathUiConverter::Fs {
        cwd: workspace_root.to_path_buf(),
        base: workspace_root.to_path_buf(),
    };
    let aliases_map: FilesetAliasesMap =
        crate::revset::load_aliases_map(settings.0.config(), "fileset-aliases");
    let context = FilesetParseContext {
        aliases_map: &aliases_map,
        path_converter: &path_converter,
    };
    let expression =
        jj_lib::fileset::parse(&mut FilesetDiagnostics::new(), &pattern, &context).map_err(|err| {
            crate::errors::JjError::new_err(format!("In `snapshot.auto-track`: {err}"))
        })?;
    Ok(expression.to_matcher())
}

/// `base_ignores` in jj's cli_util.rs: Git's `core.excludesFile` (default
/// `$XDG_CONFIG_HOME/git/ignore`) and the repo's `.git/info/exclude`.
fn base_ignores(workspace_root: &Path, store: &Store) -> PyResult<Arc<GitIgnoreFile>> {
    let excludes_file = |config: &gix::config::File| -> Option<PathBuf> {
        match config.string("core.excludesFile") {
            Some(value) => {
                let home = etcetera::home_dir().ok();
                let path = std::str::from_utf8(&value)
                    .ok()
                    .map(|path| jj_lib::file_util::expand_home_path(path, home.as_deref()))?;
                Some(workspace_root.join(path))
            }
            None => xdg_config_home().map(|dir| dir.join("git").join("ignore")),
        }
    };
    let ignore_err = |err: jj_lib::gitignore::GitIgnoreError| {
        crate::errors::JjError::new_err(err.to_string())
    };
    let mut ignores = GitIgnoreFile::empty();
    if let Ok(git_backend) = jj_lib::git::get_git_backend(store) {
        if let Some(path) = excludes_file(&git_backend.git_repo().config_snapshot()) {
            ignores = ignores.chain_with_file(RepoPath::root(), path).map_err(ignore_err)?;
        }
        ignores = ignores
            .chain_with_file(
                RepoPath::root(),
                git_backend.git_repo_path().join("info").join("exclude"),
            )
            .map_err(ignore_err)?;
    } else if let Ok(config) = gix::config::File::from_globals()
        && let Some(path) = excludes_file(&config)
    {
        ignores = ignores.chain_with_file(RepoPath::root(), path).map_err(ignore_err)?;
    }
    Ok(ignores)
}

fn xdg_config_home() -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("XDG_CONFIG_HOME")
        && !dir.is_empty()
    {
        return Some(PathBuf::from(dir));
    }
    etcetera::home_dir().ok().map(|home| home.join(".config"))
}

/// `handle_stale_working_copy` in jj's cli_util.rs: the repo and
/// working-copy commit a snapshot must start from. `None` when the
/// workspace has no working-copy commit, which jj skips silently.
fn fresh_wc_commit(
    locked_wc: &dyn LockedWorkingCopy,
    repo: Arc<ReadonlyRepo>,
    workspace_name: &WorkspaceName,
) -> PyResult<Option<(Arc<ReadonlyRepo>, Commit)>> {
    let wc_commit = |repo: &ReadonlyRepo| -> PyResult<Option<Commit>> {
        repo.view()
            .get_wc_commit_id(workspace_name)
            .map(|id| pollster::block_on(repo.store().get_commit_async(id)))
            .transpose()
            .map_err(map_backend_err)
    };
    let Some(commit) = wc_commit(&repo)? else {
        return Ok(None);
    };
    let old_op = locked_wc.old_operation_id().hex();
    let short = |hex: &str| hex[..12].to_owned();
    match pollster::block_on(WorkingCopyFreshness::check_stale(locked_wc, &commit, &repo)) {
        Ok(WorkingCopyFreshness::Fresh) => Ok(Some((repo, commit))),
        Ok(WorkingCopyFreshness::Updated(wc_op)) => {
            let repo = pollster::block_on(repo.reload_at(&wc_op))
                .map_err(crate::errors::map_repo_load_err)?;
            Ok(wc_commit(&repo)?.map(|commit| (repo, commit)))
        }
        Ok(WorkingCopyFreshness::WorkingCopyStale) => Err(WorkingCopyError::new_err(format!(
            "The working copy is stale (not updated since operation {}). \
             Run `jj workspace update-stale` to update it.",
            short(&old_op)
        ))),
        Ok(WorkingCopyFreshness::SiblingOperation) => Err(WorkingCopyError::new_err(format!(
            "The repo was loaded at operation {}, which seems to be a sibling of the \
             working copy's operation {}",
            short(&repo.op_id().hex()),
            short(&old_op)
        ))),
        Err(OpStoreError::ObjectNotFound { .. }) => Err(WorkingCopyError::new_err(
            "Could not read working copy's operation. \
             Run `jj workspace update-stale` to recover.",
        )),
        Err(err) => Err(crate::errors::map_py_err(err)),
    }
}

/// Why a path stayed untracked, worded as `jj`'s own
/// `build_untracked_reason_message` words it.
///
/// `FileNotAutoTracked` yields nothing on purpose: jj leaves that one
/// to `jj status` rather than warning about it on every snapshot.
fn untracked_reason(reason: &UntrackedReason) -> Option<String> {
    match reason {
        UntrackedReason::FileTooLarge { size, max_size } => {
            // Both spellings, as jj does, so a limit of 1MiB does not
            // read as "1.0MiB, maximum size allowed is 1.0MiB".
            let size_approx = HumanByteSize(*size);
            let max_size_approx = HumanByteSize(*max_size);
            Some(format!(
                "{size_approx} ({size} bytes); the maximum size allowed is \
                 {max_size_approx} ({max_size} bytes)"
            ))
        }
        UntrackedReason::FileNotAutoTracked => None,
    }
}

/// What `Workspace.snapshot()` did.
#[pyclass(name = "SnapshotStats", module = "pyjj_bindings", frozen, get_all)]
pub struct SnapshotOutcome {
    /// Paths the snapshot left untracked, for any reason.
    untracked_paths: usize,
    /// `{path: reason}` for files jj refused to track, such as one over
    /// `snapshot.max-new-file-size`.
    refused: std::collections::BTreeMap<String, String>,
    /// Whether the walk found anything: `jj util snapshot`'s "Snapshot
    /// complete." against "No snapshot needed.".
    changed: bool,
    /// Whether `@` was immutable, so the snapshot made a new commit on top.
    wc_immutable: bool,
    /// Descendants of `@` the snapshot rebased.
    rebased: usize,
}

impl SnapshotOutcome {
    fn new(stats: &jj_lib::working_copy::SnapshotStats) -> Self {
        Self {
            untracked_paths: stats.untracked_paths.len(),
            refused: stats
                .untracked_paths
                .iter()
                .filter_map(|(path, reason)| {
                    untracked_reason(reason)
                        .map(|message| (path.as_internal_file_string().to_owned(), message))
                })
                .collect(),
            changed: false,
            wc_immutable: false,
            rebased: 0,
        }
    }
}

/// `jj status`/`jj diff`'s implicit "snapshot the working copy" step
/// (`snapshot_working_copy` in jj's cli_util.rs), as a standalone
/// operation: reads the files on disk, rewrites the workspace's
/// working-copy commit to match, and commits that as a new operation.
///
/// Like jj, it refuses a stale working copy, reloads the repo when the
/// working copy is ahead of it, honours `snapshot.auto-track`,
/// `snapshot.max-new-file-size` and Git's global and per-repo excludes,
/// and puts a new commit on top of an immutable working-copy commit
/// instead of rewriting it (`wc_immutable` in the result).
pub fn snapshot(
    workspace: &mut Workspace,
    settings: &PyUserSettings,
    args: Option<String>,
) -> PyResult<(PyReadonlyRepo, SnapshotOutcome)> {
    let workspace_name = workspace.workspace_name().to_owned();
    let workspace_root = workspace.workspace_root().to_path_buf();
    let repo = pollster::block_on(workspace.repo_loader().load_at_head())
        .map_err(|err| crate::errors::RepoLoadError::new_err(err.to_string()))?;
    let config = SnapshotConfig::load(settings, &workspace_root, repo.store())?;
    let colocated = crate::workspace::is_colocated(workspace, repo.store())?;

    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;
    let Some((repo, old_commit)) = fresh_wc_commit(locked_ws.locked_wc(), repo, &workspace_name)?
    else {
        drop(locked_ws);
        let empty = SnapshotOutcome::new(&Default::default());
        return Ok((wrap_repo(workspace, load_head(workspace)?), empty));
    };
    let (new_tree, stats) = pollster::block_on(locked_ws.locked_wc().snapshot(&config.options()))
        .map_err(map_working_copy_err)?;
    let mut outcome = SnapshotOutcome::new(&stats);

    // Nothing changed on disk: don't rewrite the wc commit (which would
    // bump its committer timestamp and commit id for no reason) or create
    // an empty operation — just release the working-copy lock as-is.
    if new_tree.tree_ids_and_labels() == old_commit.tree().tree_ids_and_labels() {
        pollster::block_on(locked_ws.finish(repo.operation().id().clone()))
            .map_err(map_working_copy_err)?;
        return Ok((wrap_repo(workspace, repo), outcome));
    }

    let mut tx = crate::repo::open_tx(&repo, &settings.0, &workspace_name, args);
    tx.set_is_snapshot(true);
    outcome.wc_immutable = crate::rewrite::is_immutable(
        tx.repo(),
        &workspace_root,
        &workspace_name,
        settings,
        old_commit.id(),
    )?;
    let mut_repo = tx.repo_mut();
    let builder = if outcome.wc_immutable {
        mut_repo.new_commit(vec![old_commit.id().clone()], new_tree.clone())
    } else {
        mut_repo.rewrite_commit(&old_commit).set_tree(new_tree.clone())
    };
    let new_commit = pollster::block_on(builder.write()).map_err(map_backend_err)?;
    mut_repo
        .set_wc_commit(workspace_name.clone(), new_commit.id().clone())
        .map_err(|err| crate::errors::TransactionError::new_err(err.to_string()))?;
    outcome.rebased =
        pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;
    // `export_working_copy_changes_to_git` in `cli/src/cli_util.rs`:
    // without it a new file reads as untracked to `git status`.
    if colocated {
        if outcome.wc_immutable {
            crate::git::reset_head(mut_repo, workspace_name.as_str(), &workspace_root)?;
        } else {
            pollster::block_on(jj_lib::git::update_intent_to_add(
                repo.as_ref(),
                &workspace_root,
                &old_commit.tree(),
                &new_tree,
            ))
            .map_err(|err| crate::errors::JjError::new_err(err.to_string()))?;
        }
        crate::git::export_refs_only(mut_repo)?;
    }
    let new_repo = pollster::block_on(tx.commit("snapshot working copy"))
        .map_err(map_transaction_err)?;
    pollster::block_on(locked_ws.finish(new_repo.operation().id().clone()))
        .map_err(map_working_copy_err)?;
    outcome.changed = true;
    Ok((wrap_repo(workspace, new_repo), outcome))
}

fn load_head(workspace: &Workspace) -> PyResult<Arc<ReadonlyRepo>> {
    pollster::block_on(workspace.repo_loader().load_at_head())
        .map_err(|err| crate::errors::RepoLoadError::new_err(err.to_string()))
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
    let workspace_root = workspace.workspace_root().to_path_buf();
    let repo = load_head(workspace)?;
    let repo_paths = paths
        .iter()
        .map(|path| crate::tree::repo_file_path(path))
        .collect::<PyResult<Vec<_>>>()?;
    let config = SnapshotConfig::load(settings, &workspace_root, repo.store())?;
    let colocated = crate::workspace::is_colocated(workspace, repo.store())?;

    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;
    let (repo, old_commit) = fresh_wc_commit(locked_ws.locked_wc(), repo, &workspace_name)?
        .ok_or_else(|| {
            WorkingCopyError::new_err(format!(
                "Workspace `{}` has no working-copy commit",
                workspace_name.as_symbol()
            ))
        })?;

    let mut builder = MergedTreeBuilder::new(old_commit.tree());
    for repo_path in &repo_paths {
        builder.set_or_remove(repo_path.clone(), Merge::absent());
    }
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;

    let mut tx = crate::repo::open_tx(&repo, &settings.0, &workspace_name, None);
    let mut_repo = tx.repo_mut();
    let commit_builder = mut_repo.rewrite_commit(&old_commit).set_tree(new_tree);
    let new_commit = pollster::block_on(commit_builder.write()).map_err(map_backend_err)?;
    mut_repo
        .set_wc_commit(workspace_name.clone(), new_commit.id().clone())
        .map_err(|err| crate::errors::TransactionError::new_err(err.to_string()))?;
    pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;

    pollster::block_on(locked_ws.locked_wc().reset(&new_commit)).map_err(map_working_copy_err)?;

    let (snapshot_tree, _stats) = pollster::block_on(locked_ws.locked_wc().snapshot(&config.options()))
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

    // `finish_transaction`: a moved `@` resets Git HEAD and the index.
    if colocated {
        crate::git::reset_head(mut_repo, workspace_name.as_str(), &workspace_root)?;
        crate::git::export_refs_only(mut_repo)?;
    }
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
) -> PyResult<CheckoutStats> {
    let operation_id = repo.inner.operation().id().clone();
    pollster::block_on(workspace.check_out(operation_id, None, &commit.inner))
        .map_err(map_checkout_err)
}

/// `jj sparse set`: replace the sparse patterns and update the files on
/// disk to match. Records no operation.
pub fn set_sparse_patterns(
    workspace: &mut Workspace,
    patterns: Vec<RepoPathBuf>,
) -> PyResult<CheckoutStats> {
    let mut locked_ws = pollster::block_on(workspace.start_working_copy_mutation())
        .map_err(map_working_copy_err)?;
    let stats = pollster::block_on(locked_ws.locked_wc().set_sparse_patterns(patterns))
        .map_err(map_checkout_err)?;
    let operation_id = locked_ws.locked_wc().old_operation_id().clone();
    pollster::block_on(locked_ws.finish(operation_id)).map_err(map_working_copy_err)?;
    Ok(stats)
}

/// `{"updated_files", "added_files", "removed_files", "skipped_files"}`.
/// What a checkout did to the files on disk.
#[pyclass(name = "CheckoutStats", module = "pyjj_bindings", frozen, get_all)]
pub struct PyCheckoutStats {
    pub updated_files: u32,
    pub added_files: u32,
    pub removed_files: u32,
    /// Files left alone because they were not what jj expected on disk.
    pub skipped_files: u32,
}

impl From<CheckoutStats> for PyCheckoutStats {
    fn from(stats: CheckoutStats) -> Self {
        Self {
            updated_files: stats.updated_files,
            added_files: stats.added_files,
            removed_files: stats.removed_files,
            skipped_files: stats.skipped_files,
        }
    }
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
