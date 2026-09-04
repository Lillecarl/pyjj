//! The isolated working copies `jj run` executes commands in.
//!
//! `jj run` cannot use the real working copy: it visits many commits, and
//! a real workspace would show up in the repository view. So it keeps its
//! own pool of bare checkouts under `.jj/run/default/<n>/`, each one a
//! `jj_lib::local_working_copy::TreeState` with no workspace and no view
//! entry. That is the part that has to live in Rust -- checking a tree out
//! to disk and snapshotting it back is jj_lib's, not Python's.
//!
//! Python drives the rest: it acquires a slot, runs the subprocess, and
//! asks for the resulting tree id. `Transaction.run_rewrite()` then writes
//! the new trees onto the commits, which is the other half that needs
//! jj_lib (`transform_descendants` and its per-commit rebase/reparent
//! choice).
//!
//! Slots persist between `jj run` invocations, so a build tree survives
//! and the next run only rewrites the files that changed. `clean` turns
//! that off.

use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::sync::Arc;

use futures::StreamExt as _;
use pyo3::prelude::*;

use jj_lib::backend::CommitId;
use jj_lib::commit::Commit;
use jj_lib::conflicts::ConflictMarkerStyle;
use jj_lib::fsmonitor::FsmonitorSettings;
use jj_lib::gitignore::GitIgnoreFile;
use jj_lib::local_working_copy::{
    EolConversionMode, ExecChangeSetting, TreeState, TreeStateSettings,
};
use jj_lib::lock::FileLock;
use jj_lib::matchers::{EverythingMatcher, NothingMatcher};
use jj_lib::merge::Merge;
use jj_lib::merged_tree::MergedTree;
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::working_copy::SnapshotOptions;

use crate::commit::PyCommit;
use crate::errors::{map_backend_err, map_py_err};
use crate::ids::PyTreeId;

/// The tree-state settings a run slot uses.
///
/// Hardcoded, exactly as `cli/src/commands/run.rs` hardcodes them: a run
/// slot is a scratch checkout, so the user's conflict-marker style, EOL
/// conversion and fsmonitor have no business changing what the command
/// sees or what comes back.
fn slot_tree_state_settings() -> TreeStateSettings {
    TreeStateSettings {
        conflict_marker_style: ConflictMarkerStyle::Snapshot,
        eol_conversion_mode: EolConversionMode::None,
        exec_change_setting: ExecChangeSetting::Auto,
        fsmonitor_settings: FsmonitorSettings::None,
    }
}

/// The literal value `jj run` passes for `max_new_file_size`.
///
/// jj's own comment there says "64 MB for now"; the number is 64 kB. The
/// number is what decides which files a command's output can add to a
/// commit, so pyjj copies the number and not the comment.
const MAX_NEW_FILE_SIZE: u64 = 64_000;

fn snapshot_options<'a>(base_ignores: &Arc<GitIgnoreFile>) -> SnapshotOptions<'a> {
    SnapshotOptions {
        base_ignores: base_ignores.clone(),
        // `snapshot.auto-track` support is missing here for the same
        // reason it is missing in `checkout.rs`: jj's own default is
        // `all()`, so every non-ignored new file is tracked.
        start_tracking_matcher: &EverythingMatcher,
        progress: None,
        max_new_file_size: MAX_NEW_FILE_SIZE,
        force_tracking_matcher: &NothingMatcher,
    }
}

/// A fixed-size pool of scratch checkouts under `.jj/run/default/`.
///
/// Slot `n` is `<n>/working_copy` plus `<n>/state`, and its lock is the
/// sibling file `<n>.lock`. Slots are numbered from 1, same as jj. The
/// lock is an interprocess one, so two `jj run` processes on the same
/// repository share the pool instead of fighting over it.
#[pyclass(name = "RunPool", unsendable)]
pub struct PyRunPool {
    base_path: PathBuf,
    size: usize,
    clean: bool,
}

#[pymethods]
impl PyRunPool {
    /// `repo_path` is the `.jj/repo` directory (`Workspace.repo_path`).
    /// The pool lives beside it, under `.jj/run`, never inside it.
    #[new]
    #[pyo3(signature = (repo_path, size, clean=false))]
    fn new(repo_path: &str, size: usize, clean: bool) -> PyResult<Self> {
        if size == 0 {
            return Err(crate::errors::JjError::new_err(
                "run pool size must be at least 1",
            ));
        }
        let base_path = PathBuf::from(repo_path)
            .parent()
            .ok_or_else(|| crate::errors::JjError::new_err("repo path has no parent"))?
            .join("run")
            .join("default");
        fs::create_dir_all(&base_path).map_err(map_py_err)?;
        Ok(Self {
            base_path,
            size,
            clean,
        })
    }

    /// Take a free slot and check `commit`'s tree out into it.
    ///
    /// Blocks until a slot frees up. Release the returned slot (by
    /// `finish()` or `discard()`) before acquiring another one, or a
    /// single-slot pool deadlocks.
    fn acquire(&self, py: Python<'_>, commit: &PyCommit) -> PyResult<PyRunSlot> {
        py.detach(|| self.acquire_inner(&commit.inner))
    }
}

impl PyRunPool {
    fn acquire_inner(&self, commit: &Commit) -> PyResult<PyRunSlot> {
        let (slot_index, lock) = self.acquire_any_slot()?;
        let slot_path = self.base_path.join(slot_index.to_string());
        let working_copy_dir = slot_path.join("working_copy");
        let state_dir = slot_path.join("state");
        let tree_state_path = state_dir.join("tree_state");
        let base_ignores = GitIgnoreFile::empty();

        let is_reused = tree_state_path.exists();
        let settings = slot_tree_state_settings();
        let mut tree_state = if !self.clean && is_reused {
            // Load the state the last job left, so the checkout below
            // only touches files that actually differ.
            //
            // Then delete `tree_state` from disk. Its absence is the
            // dirty marker: if this process dies before `finish()` saves
            // it again, the next acquisition sees no state file and
            // wipes the slot instead of trusting a half-written tree.
            let loaded = TreeState::load(
                commit.store().clone(),
                working_copy_dir.clone(),
                state_dir.clone(),
                &settings,
            )
            .map_err(map_py_err)?;
            fs::remove_file(&tree_state_path).map_err(map_py_err)?;
            loaded
        } else {
            // First use, a crashed predecessor, or `clean`. Wipe
            // whatever is there and start from an empty in-memory state,
            // which stays off disk until `finish()` writes it.
            remove_if_present(&tree_state_path)?;
            remove_dir_if_present(&working_copy_dir)?;
            remove_dir_if_present(&state_dir)?;
            fs::create_dir_all(&working_copy_dir).map_err(map_py_err)?;
            fs::create_dir_all(&state_dir).map_err(map_py_err)?;
            TreeState::init_without_saving(
                commit.store().clone(),
                working_copy_dir.clone(),
                state_dir,
                &settings,
            )
        };

        tree_state.check_out(&commit.tree()).map_err(map_py_err)?;

        // Checking out an empty tree deletes the slot directory itself:
        // `check_out` removes empty directories until something stops
        // it, and a slot has no `.jj` to stop it. Put it back.
        fs::create_dir_all(&working_copy_dir).map_err(map_py_err)?;

        if is_reused {
            remove_newly_ignored_files(&mut tree_state, commit, &working_copy_dir, &base_ignores)?;
        }

        Ok(PyRunSlot {
            working_copy_dir,
            tree_state: Some(tree_state),
            lock: Some(lock),
            base_ignores,
        })
    }

    /// Lock the first free slot, waiting if every slot is busy.
    fn acquire_any_slot(&self) -> PyResult<(usize, FileLock)> {
        let mut backoff = std::time::Duration::from_millis(10);
        let max_backoff = std::time::Duration::from_millis(250);
        loop {
            for slot in 1..=self.size {
                let slot_path = self.base_path.join(slot.to_string());
                fs::create_dir_all(&slot_path).map_err(map_py_err)?;
                let lock_path = self.base_path.join(format!("{slot}.lock"));
                if let Some(lock) = FileLock::try_lock(lock_path).map_err(map_py_err)? {
                    return Ok((slot, lock));
                }
            }
            std::thread::sleep(backoff);
            backoff = std::cmp::min(backoff * 2, max_backoff);
        }
    }
}

/// Delete files the previous job left behind that the new commit does not
/// ignore.
///
/// A slot keeps ignored build artifacts on purpose. But a file that was
/// ignored under the old commit and is not ignored under the new one would
/// silently become part of the new commit. jj finds those by snapshotting
/// after the checkout, diffing against the commit's own tree, deleting
/// whatever the snapshot added, and checking out again to reset the state.
fn remove_newly_ignored_files(
    tree_state: &mut TreeState,
    commit: &Commit,
    working_copy_dir: &std::path::Path,
    base_ignores: &Arc<GitIgnoreFile>,
) -> PyResult<()> {
    let options = snapshot_options(base_ignores);
    pollster::block_on(tree_state.snapshot(&options)).map_err(map_py_err)?;
    let post_snapshot_tree = tree_state.current_tree().clone();
    let original_tree = commit.tree();

    let added_paths = pollster::block_on(async {
        let mut diff = original_tree.diff_stream(&post_snapshot_tree, &EverythingMatcher);
        let mut added = Vec::new();
        while let Some(entry) = diff.next().await {
            let values = entry.values.map_err(map_backend_err)?;
            if values.before.is_absent() && values.after.is_present() {
                added.push(entry.path);
            }
        }
        Ok::<_, PyErr>(added)
    })?;

    for path in &added_paths {
        remove_if_present(&path.to_fs_path_unchecked(working_copy_dir))?;
    }
    if !added_paths.is_empty() {
        tree_state
            .check_out(&original_tree)
            .map_err(map_py_err)?;
    }
    Ok(())
}

fn remove_if_present(path: &std::path::Path) -> PyResult<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(map_py_err(err)),
    }
}

fn remove_dir_if_present(path: &std::path::Path) -> PyResult<()> {
    match fs::remove_dir_all(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(map_py_err(err)),
    }
}

/// One checked-out slot, held for the duration of one command.
///
/// The slot holds its interprocess lock until `finish()` or `discard()`.
/// Neither is optional: a slot that is never released keeps the lock for
/// the life of the process.
#[pyclass(name = "RunSlot", unsendable)]
pub struct PyRunSlot {
    working_copy_dir: PathBuf,
    tree_state: Option<TreeState>,
    lock: Option<FileLock>,
    base_ignores: Arc<GitIgnoreFile>,
}

#[pymethods]
impl PyRunSlot {
    /// The directory the command should run in (or under).
    #[getter]
    fn working_copy_dir(&self) -> String {
        self.working_copy_dir.to_string_lossy().into_owned()
    }

    /// Snapshot the slot after the command ran, then release it.
    ///
    /// Returns `(dirty, tree_id)`. `dirty` says whether the command
    /// touched any tracked file. `tree_id` is the resulting tree, and is
    /// `None` when `success` is false -- a failed command's output must
    /// not reach a commit.
    ///
    /// When `success` is false the untracked files the command left are
    /// deleted as well. Ignored paths are not in that set, so build
    /// artifacts survive; what goes is the half-written output that would
    /// otherwise collide with the next checkout.
    ///
    /// The state is saved either way, so the slot stays reusable.
    fn finish(&mut self, py: Python<'_>, success: bool) -> PyResult<(bool, Option<PyTreeId>)> {
        let base_ignores = self.base_ignores.clone();
        let working_copy_dir = self.working_copy_dir.clone();
        let tree_state = self.tree_state.as_mut().ok_or_else(|| {
            crate::errors::JjError::new_err("run slot already released")
        })?;
        let result = py.detach(|| {
            let options = snapshot_options(&base_ignores);
            let (dirty, stats) =
                pollster::block_on(tree_state.snapshot(&options)).map_err(map_py_err)?;
            if !success {
                for path in stats.untracked_paths.keys() {
                    remove_if_present(&path.to_fs_path_unchecked(&working_copy_dir))?;
                }
            }
            tree_state.save().map_err(map_py_err)?;
            let tree_id = if success {
                let ids = tree_state.current_tree().tree_ids();
                ids.as_resolved().map(|id| PyTreeId(id.clone()))
            } else {
                None
            };
            Ok::<_, PyErr>((dirty, tree_id))
        });
        self.release();
        result
    }

    /// Release the slot without snapshotting, saving the post-checkout
    /// state so the next acquisition can still diff against it.
    ///
    /// This is the skipped-commit path: the command never ran, so there
    /// is nothing to snapshot, but the tree on disk is a real checkout.
    fn discard(&mut self) -> PyResult<()> {
        if let Some(tree_state) = self.tree_state.as_mut() {
            tree_state.save().map_err(map_py_err)?;
        }
        self.release();
        Ok(())
    }

    fn __repr__(&self) -> String {
        format!("RunSlot({})", self.working_copy_dir.to_string_lossy())
    }
}

impl PyRunSlot {
    fn release(&mut self) {
        self.tree_state = None;
        self.lock = None;
    }
}

/// `jj run`'s rewrite half: put each command's resulting tree onto its
/// commit, and carry the change into the descendants.
///
/// `targets` is the revset `jj run` was given -- the roots
/// `transform_descendants` walks from. `new_trees` maps a target's commit
/// id (hex) to the tree its command produced; a target whose command
/// changed nothing is simply absent.
///
/// `restore_descendants` picks between two readings of "carry the change
/// into the descendants":
///
/// * false (the default) is *propagate the diff*. A rewritten commit gets
///   the merge of its command result, its original tree and its rebased
///   tree, so an ancestor's rewrite and the command's own edit both land.
///   Descendants outside the set are rebased normally.
/// * true is *keep the content*. A rewritten commit gets the command
///   result verbatim, ignoring what happened to its ancestors, and
///   descendants outside the set are reparented, so their trees do not
///   move at all.
///
/// Returns `(rewritten, reparented)`.
pub fn run_rewrite(
    mut_repo: &mut MutableRepo,
    targets: Vec<crate::ids::PyCommitId>,
    new_trees: HashMap<String, PyTreeId>,
    restore_descendants: bool,
) -> PyResult<(u32, u32)> {
    let store = mut_repo.store().clone();
    let roots: Vec<CommitId> = targets.into_iter().map(|id| id.0).collect();
    let new_trees: HashMap<CommitId, jj_lib::backend::TreeId> = new_trees
        .into_iter()
        .map(|(hex, tree_id)| {
            CommitId::try_from_hex(&hex)
                .map(|id| (id, tree_id.0))
                .ok_or_else(|| crate::errors::JjError::new_err(format!("invalid CommitId: {hex}")))
        })
        .collect::<PyResult<_>>()?;

    let rewritten = std::cell::Cell::new(0u32);
    let reparented = std::cell::Cell::new(0u32);
    pollster::block_on(mut_repo.transform_descendants(roots, async |rewriter| {
        let old_id = rewriter.old_commit().id().clone();
        let old_tree = rewriter.old_commit().tree();
        match (new_trees.get(&old_id), restore_descendants) {
            (Some(new_tree_id), true) => {
                let builder = rewriter.rebase().await?;
                rewritten.set(rewritten.get() + 1);
                builder
                    .set_tree(MergedTree::resolved(store.clone(), new_tree_id.clone()))
                    .write()
                    .await?;
            }
            (Some(new_tree_id), false) => {
                let builder = rewriter.rebase().await?;
                rewritten.set(rewritten.get() + 1);
                let rebased_tree = builder.tree();
                let merged = MergedTree::merge(Merge::from_vec(vec![
                    (
                        MergedTree::resolved(store.clone(), new_tree_id.clone()),
                        "command result".to_owned(),
                    ),
                    (old_tree, "original commit".to_owned()),
                    (rebased_tree, "rebased".to_owned()),
                ]))
                .await?;
                builder.set_tree(merged).write().await?;
            }
            (None, true) => {
                rewriter.reparent().write().await?;
                reparented.set(reparented.get() + 1);
            }
            (None, false) => {
                rewriter.rebase().await?.write().await?;
            }
        }
        Ok(())
    }))
    .map_err(map_backend_err)?;

    Ok((rewritten.into_inner(), reparented.into_inner()))
}
