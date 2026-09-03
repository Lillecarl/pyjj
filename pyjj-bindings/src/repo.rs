use std::cell::RefCell;
use std::sync::Arc;

use pyo3::prelude::*;

use jj_lib::backend::CommitId;
use jj_lib::commit::Commit;
use jj_lib::commit_builder::CommitBuilder;
use jj_lib::object_id::ObjectId as _;
use jj_lib::op_store::RefTarget;
use jj_lib::ref_name::RefName;
use jj_lib::repo::{MutableRepo, ReadonlyRepo, Repo as _};
use jj_lib::transaction::Transaction;

use crate::bookmark::PyBookmark;
use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_backend_err, map_index_err, map_py_err, map_repo_load_err, map_transaction_err};
use crate::ids::{PyChangeId, PyCommitId, PySignature};
use crate::settings::PyUserSettings;

// ── ReadonlyRepo ────────────────────────────────────────────────────────────

impl PyReadonlyRepo {
    /// Build the disambiguation context `shortest_*_prefix_len` shortens
    /// within, following `jj`'s own rule: `revsets.short-prefixes` if
    /// set, otherwise `revsets.log`, and no narrowing at all when the
    /// chosen one is empty or no settings were given.
    fn id_prefix_context(
        &self,
        settings: Option<&PyUserSettings>,
    ) -> PyResult<jj_lib::id_prefix::IdPrefixContext> {
        use jj_lib::id_prefix::IdPrefixContext;
        use jj_lib::revset::RevsetExtensions;

        let context = IdPrefixContext::new(std::sync::Arc::new(RevsetExtensions::new()));
        let Some(settings) = settings else {
            return Ok(context);
        };
        let revset_string = match settings.0.get_string("revsets.short-prefixes") {
            Ok(value) => value,
            Err(_) => settings
                .0
                .get_string("revsets.log")
                .unwrap_or_else(|_| String::new()),
        };
        if revset_string.is_empty() {
            return Ok(context);
        }
        let expression = crate::revset::parse_revset(
            &self.workspace_root,
            &self.workspace_name,
            settings,
            &revset_string,
        )?;
        Ok(context.disambiguate_within(expression))
    }

}

#[pymethods]
impl PyReadonlyRepo {
    /// Start a new transaction to make changes to the repo.
    fn start_transaction(&self, settings: &PyUserSettings) -> PyTransaction {
        let base = self.inner.clone();
        let index = base.readonly_index();
        let view = base.view();
        let mut_repo = MutableRepo::new(base.clone(), index, view);
        let tx = Transaction::new(mut_repo, &settings.0);
        PyTransaction {
            inner: RefCell::new(Some(tx)),
            base_repo: base,
            workspace_root: self.workspace_root.clone(),
            workspace_name: self.workspace_name.clone(),
        }
    }

    /// Get the current view summary (workspace→commit mapping).
    fn view(&self) -> PyResult<Py<PyAny>> {
        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            let view = self.inner.view();
            for (ws_name, commit_id) in view.wc_commit_ids() {
                let key: &str = ws_name.as_ref();
                let val = commit_id.hex();
                dict.set_item(key, val)?;
            }
            Ok(dict.unbind().into_any())
        })
    }

    /// Look up a commit by its [`CommitId`].
    fn get_commit(&self, commit_id: &PyCommitId) -> PyResult<PyCommit> {
        let commit = pollster::block_on(self.inner.store().get_commit_async(&commit_id.0))
            .map_err(map_backend_err)?;
        Ok(PyCommit {
            inner: commit,
            _repo: Some(self.inner.clone()),
        })
    }

    /// Async sibling of `get_commit()`. Runs on tokio's blocking thread
    /// pool (see `aio` module docs) rather than on the calling thread, so
    /// the event loop isn't blocked for the duration of the backend read.
    fn get_commit_async<'py>(
        &self,
        py: Python<'py>,
        commit_id: PyCommitId,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.inner.clone();
        crate::aio::spawn_blocking_py(py, move || {
            let commit = pollster::block_on(repo.store().get_commit_async(&commit_id.0))
                .map_err(map_backend_err)?;
            Ok(PyCommit {
                inner: commit,
                _repo: Some(repo),
            })
        })
    }

    /// Parse and evaluate a revset expression (e.g. `"@"`, `"main"`,
    /// `"ancestors(@, 5)"`), returning matching commits in topological
    /// (children-before-parents) order.
    fn revset(&self, settings: &PyUserSettings, revision: &str) -> PyResult<Vec<PyCommit>> {
        crate::revset::evaluate_revset(self, settings, revision)
    }

    /// Async sibling of `revset()`. See `get_commit_async()`'s docs for why
    /// this runs on tokio's blocking thread pool rather than directly.
    fn revset_async<'py>(
        &self,
        py: Python<'py>,
        settings: &PyUserSettings,
        revision: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.clone();
        let settings = PyUserSettings(settings.0.clone());
        crate::aio::spawn_blocking_py(py, move || {
            crate::revset::evaluate_revset(&repo, &settings, &revision)
        })
    }

    /// Like `revset()`, but each commit comes with edges to its relevant
    /// ancestors instead of being a flat list -- see
    /// `pyjj_bindings.graph::log_graph`'s docs for the exact edge/ordering
    /// semantics (same primitives `jj log`'s own graph is built on).
    /// `limit`, if given, stops after that many rows.
    #[pyo3(signature = (settings, revision, limit=None))]
    fn log_graph(
        &self,
        settings: &PyUserSettings,
        revision: &str,
        limit: Option<usize>,
    ) -> PyResult<Vec<crate::graph::PyGraphNode>> {
        crate::graph::log_graph(self, settings, revision, limit)
    }

    /// How the given commits evolved: every earlier version of each
    /// change, newest first, the way `jj evolog` shows it. See
    /// `EvolutionEntry`. `limit` stops after that many entries.
    #[pyo3(signature = (start_commits, limit=None))]
    fn evolution_log(
        &self,
        start_commits: Vec<PyCommitId>,
        limit: Option<usize>,
    ) -> PyResult<Vec<crate::evolution::PyEvolutionEntry>> {
        crate::evolution::evolution_log(self, start_commits, limit)
    }

    /// Async sibling of `log_graph()`. See `get_commit_async()`'s docs for
    /// why this runs on tokio's blocking thread pool rather than directly.
    #[pyo3(signature = (settings, revision, limit=None))]
    fn log_graph_async<'py>(
        &self,
        py: Python<'py>,
        settings: &PyUserSettings,
        revision: String,
        limit: Option<usize>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.clone();
        let settings = PyUserSettings(settings.0.clone());
        crate::aio::spawn_blocking_py(py, move || {
            crate::graph::log_graph(&repo, &settings, &revision, limit)
        })
    }

    /// All local bookmarks, in lexicographical order.
    fn bookmarks(&self) -> Vec<PyBookmark> {
        self.inner
            .view()
            .local_bookmarks()
            .map(|(name, target)| PyBookmark::from_target(name, target))
            .collect()
    }

    /// `jj interdiff --from A --to B`: how the changes `from` makes
    /// differ from the changes `to` makes. Unlike a plain diff, this
    /// leaves out whatever changed between the two commits' parents.
    #[pyo3(signature = (from, to, paths=None))]
    fn interdiff(
        &self,
        from: &PyCommit,
        to: &PyCommit,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        crate::tree::interdiff_commits(self, from, to, paths)
    }

    /// All local tags, in lexicographical order. Tags are typically
    /// populated by `git_import_refs()` from real Git tags, though nothing
    /// prevents setting them by hand via `Transaction.set_tag()`.
    fn tags(&self) -> Vec<crate::tag::PyTag> {
        self.inner
            .view()
            .local_tags()
            .map(|(name, target)| crate::tag::PyTag::from_target(name, target))
            .collect()
    }

    /// The named local tag, or `None` if it doesn't exist.
    fn get_tag(&self, name: &str) -> Option<crate::tag::PyTag> {
        let ref_name = RefName::new(name);
        let target = self.inner.view().get_local_tag(ref_name);
        if target.is_absent() {
            None
        } else {
            Some(crate::tag::PyTag::from_target(ref_name, target))
        }
    }

    /// Names of all configured Git remotes.
    fn git_remotes(&self) -> PyResult<Vec<String>> {
        crate::git::list_remotes(self.inner.store())
    }

    /// The named local bookmark, or `None` if it doesn't exist.
    fn get_bookmark(&self, name: &str) -> Option<PyBookmark> {
        let ref_name = RefName::new(name);
        let target = self.inner.view().get_local_bookmark(ref_name);
        if target.is_absent() {
            None
        } else {
            Some(PyBookmark::from_target(ref_name, target))
        }
    }

    /// Convenience for revsets expected to resolve to exactly one commit.
    /// Raises `RevsetEvalError` if the revset matched zero or more than one
    /// commit.
    fn resolve_single(&self, settings: &PyUserSettings, revision: &str) -> PyResult<PyCommit> {
        let mut commits = crate::revset::evaluate_revset(self, settings, revision)?;
        match commits.len() {
            1 => Ok(commits.pop().unwrap()),
            0 => Err(crate::errors::RevsetEvalError::new_err(format!(
                "revset `{revision}` didn't resolve to any revisions"
            ))),
            n => Err(crate::errors::RevsetEvalError::new_err(format!(
                "revset `{revision}` resolved to {n} revisions, expected exactly one"
            ))),
        }
    }

    /// Async sibling of `resolve_single()`. See `get_commit_async()`'s docs
    /// for why this runs on tokio's blocking thread pool rather than
    /// directly.
    fn resolve_single_async<'py>(
        &self,
        py: Python<'py>,
        settings: &PyUserSettings,
        revision: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.clone();
        let settings = PyUserSettings(settings.0.clone());
        crate::aio::spawn_blocking_py(py, move || {
            let mut commits = crate::revset::evaluate_revset(&repo, &settings, &revision)?;
            match commits.len() {
                1 => Ok(commits.pop().unwrap()),
                0 => Err(crate::errors::RevsetEvalError::new_err(format!(
                    "revset `{revision}` didn't resolve to any revisions"
                ))),
                n => Err(crate::errors::RevsetEvalError::new_err(format!(
                    "revset `{revision}` resolved to {n} revisions, expected exactly one"
                ))),
            }
        })
    }

    /// The operation this repo was loaded at (the current head of `jj op
    /// log`, from this repo's point of view).
    #[getter]
    fn operation(&self) -> crate::operation::PyOperation {
        crate::operation::PyOperation(self.inner.operation().clone())
    }

    /// The shortest prefix length (in hex characters) of `commit_id` that
    /// still resolves to it -- pass this to `CommitId.short()` to get the
    /// same "shortest unique prefix" `jj log` highlights.
    ///
    /// Without `settings`, this disambiguates against every commit in the
    /// repo. Pass `settings` to narrow it the way `jj` does: the
    /// `revsets.short-prefixes` revset, or `revsets.log` when that is
    /// unset, becomes the set ids are shortened within, so a small
    /// working set gets short ids even in a large repo. An empty string
    /// for either turns the narrowing off.
    ///
    /// Either way the result is widened past any prefix that a bookmark
    /// or tag name would shadow, since such a prefix would no longer
    /// resolve to the commit.
    #[pyo3(signature = (commit_id, settings=None))]
    fn shortest_commit_id_prefix_len(
        &self,
        commit_id: &PyCommitId,
        settings: Option<&PyUserSettings>,
    ) -> PyResult<usize> {
        let context = self.id_prefix_context(settings)?;
        let index = context.populate(self.inner.as_ref()).map_err(map_py_err)?;
        index
            .shortest_commit_prefix_len(self.inner.as_ref(), &commit_id.0)
            .map_err(map_index_err)
    }

    /// Change-id equivalent of `shortest_commit_id_prefix_len()` -- pass
    /// the result to `ChangeId.reverse_hex()[:n]` (jj displays change ids
    /// reversed, so the *shortest unique prefix* is the leading `n`
    /// characters of the already-reversed hex string, same as `jj log`).
    #[pyo3(signature = (change_id, settings=None))]
    fn shortest_change_id_prefix_len(
        &self,
        change_id: &PyChangeId,
        settings: Option<&PyUserSettings>,
    ) -> PyResult<usize> {
        let context = self.id_prefix_context(settings)?;
        let index = context.populate(self.inner.as_ref()).map_err(map_py_err)?;
        index
            .shortest_change_prefix_len(self.inner.as_ref(), &change_id.0)
            .map_err(map_index_err)
    }

    /// The full operation log, walked backward from `self.operation`,
    /// newest first -- same order as `jj op log`.
    fn operation_log(&self) -> PyResult<Vec<crate::operation::PyOperation>> {
        crate::oplog::operation_log(self.inner.as_ref())
    }

    /// Async sibling of `operation_log()`. See `get_commit_async()`'s docs
    /// for why this runs on tokio's blocking thread pool rather than
    /// directly.
    fn operation_log_async<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.inner.clone();
        crate::aio::spawn_blocking_py(py, move || crate::oplog::operation_log(repo.as_ref()))
    }

    /// Loads an arbitrary past operation by its full hex id (see
    /// `Operation.id` / `operation_log()`).
    fn load_operation(&self, op_id: &str) -> PyResult<crate::operation::PyOperation> {
        crate::oplog::load_operation(self.inner.as_ref(), op_id)
    }

    /// Async sibling of `load_operation()`. See `get_commit_async()`'s docs
    /// for why this runs on tokio's blocking thread pool rather than
    /// directly.
    fn load_operation_async<'py>(
        &self,
        py: Python<'py>,
        op_id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.inner.clone();
        crate::aio::spawn_blocking_py(py, move || {
            crate::oplog::load_operation(repo.as_ref(), &op_id)
        })
    }

    /// `jj --at-op=<id>` equivalent: loads a full read-only repo view as it
    /// was at `op` (from `operation_log()`/`load_operation()`), not just
    /// this repo's current head. Purely read-only historical inspection --
    /// doesn't touch the working copy or move any workspace's current
    /// operation; use `Transaction.restore_operation()` (and commit it) if
    /// you actually want to move the repo backward.
    fn load_at_operation(&self, op: &crate::operation::PyOperation) -> PyResult<PyReadonlyRepo> {
        let repo =
            pollster::block_on(self.inner.loader().load_at(&op.0)).map_err(map_repo_load_err)?;
        Ok(PyReadonlyRepo {
            inner: repo,
            workspace_root: self.workspace_root.clone(),
            workspace_name: self.workspace_name.clone(),
        })
    }

    /// Async sibling of `load_at_operation()`. See `get_commit_async()`'s
    /// docs for why this runs on tokio's blocking thread pool rather than
    /// directly.
    fn load_at_operation_async<'py>(
        &self,
        py: Python<'py>,
        op: crate::operation::PyOperation,
    ) -> PyResult<Bound<'py, PyAny>> {
        let repo = self.clone();
        crate::aio::spawn_blocking_py(py, move || {
            let loaded = pollster::block_on(repo.inner.loader().load_at(&op.0))
                .map_err(map_repo_load_err)?;
            Ok(PyReadonlyRepo {
                inner: loaded,
                workspace_root: repo.workspace_root.clone(),
                workspace_name: repo.workspace_name.clone(),
            })
        })
    }

    /// Hex id of the operation this repo view was loaded at.
    ///
    /// `jj` abbreviates this to 12 characters when it prints an
    /// `jj op restore` hint.
    #[getter]
    fn operation_id(&self) -> String {
        self.inner.operation().id().hex()
    }

    fn __repr__(&self) -> String {
        format!("ReadonlyRepo(op={})", self.inner.operation().id().hex())
    }
}

// ── Transaction ─────────────────────────────────────────────────────────────

/// A mutable transaction on a repo.
///
/// Combines `Transaction` and `MutableRepo` — you can create commits,
/// modify refs, rebase, and finally `commit()` to publish.
///
/// Not thread-safe — bound to the thread that created it.
#[pyclass(name = "Transaction", unsendable)]
pub struct PyTransaction {
    /// Using RefCell so we can take ownership for commit() while still
    /// allowing &mut access to the inner MutableRepo for builder methods.
    inner: RefCell<Option<Transaction>>,
    #[allow(dead_code)]
    base_repo: Arc<ReadonlyRepo>,
    workspace_root: std::path::PathBuf,
    workspace_name: jj_lib::ref_name::WorkspaceNameBuf,
}

// Helper to get a &mut MutableRepo from the RefCell<Option<Transaction>>
fn with_mut_repo<F, R>(tx: &PyTransaction, f: F) -> PyResult<R>
where
    F: FnOnce(&mut MutableRepo) -> PyResult<R>,
{
    let mut opt = tx.inner.borrow_mut();
    let tx_ref = opt
        .as_mut()
        .ok_or_else(|| crate::errors::TransactionError::new_err("Transaction already consumed"))?;
    f(tx_ref.repo_mut())
}

impl PyTransaction {
    pub(crate) fn workspace_root(&self) -> &std::path::Path {
        &self.workspace_root
    }

    pub(crate) fn workspace_name(&self) -> &jj_lib::ref_name::WorkspaceNameBuf {
        &self.workspace_name
    }
}

#[pymethods]
impl PyTransaction {
    /// Create a new commit with the given parent IDs. With more than one
    /// parent, the initial tree is their actual merge (auto-resolving what
    /// it can, same as `jj new <rev1> <rev2> ...`) -- not just the first
    /// parent's tree -- so paths the parents changed differently come out
    /// conflicted, same as real jj.
    /// Returns a [`CommitBuilder`] for further configuration.
    fn new_commit(
        &self,
        _settings: &PyUserSettings,
        parent_ids: Vec<PyCommitId>,
    ) -> PyResult<PyCommitBuilder> {
        let parents: Vec<CommitId> = parent_ids.into_iter().map(|p| p.0).collect();
        if parents.is_empty() {
            return Err(crate::errors::TransactionError::new_err(
                "new_commit requires at least one parent",
            ));
        }
        with_mut_repo(self, |mut_repo| {
            let commits: Vec<Commit> = parents
                .iter()
                .map(|id| {
                    pollster::block_on(mut_repo.base_repo().store().get_commit_async(id))
                        .map_err(map_backend_err)
                })
                .collect::<PyResult<_>>()?;
            let tree = pollster::block_on(jj_lib::rewrite::merge_commit_trees(mut_repo, &commits))
                .map_err(map_backend_err)?;
            let builder = mut_repo.new_commit(parents, tree);
            Ok(PyCommitBuilder::from_rust(builder))
        })
    }

    /// Rewrite an existing commit. Returns a [`CommitBuilder`].
    fn rewrite_commit(
        &self,
        _settings: &PyUserSettings,
        predecessor: &PyCommit,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            let builder = mut_repo.rewrite_commit(&predecessor.inner);
            Ok(PyCommitBuilder::from_rust(builder))
        })
    }

    /// Set the working-copy commit for a workspace. A lower-level primitive
    /// than `edit()` — it doesn't auto-abandon whatever commit the
    /// workspace was previously pointing at, even if that commit is now an
    /// orphaned, empty, undescribed head. Most callers advancing the
    /// working copy (`jj new`/`jj describe`-workflow) want `edit()` instead.
    fn set_wc_commit(&self, workspace_name: String, commit_id: &PyCommitId) -> PyResult<()> {
        use jj_lib::ref_name::WorkspaceNameBuf;
        let name = WorkspaceNameBuf::from(workspace_name.as_str());
        with_mut_repo(self, |mut_repo| {
            mut_repo
                .set_wc_commit(name, commit_id.0.clone())
                .map_err(map_transaction_err)?;
            Ok(())
        })
    }

    /// `jj new <rev>`/`jj edit <rev>`'s core semantic: point a workspace's
    /// working-copy commit at `commit` (registering it as a repo head if
    /// it isn't already), *and* abandon the commit the workspace was
    /// previously pointing at if it's discardable (empty + no description),
    /// not referenced by a bookmark/tag/another workspace, and *still a
    /// head* at this point — same as `MutableRepo::edit`'s own doc comment
    /// describes. That head-check is why advancing forward with a plain
    /// child of the current wc (the everyday `jj new` case) does *not*
    /// abandon the old commit (writing the child already made it non-head,
    /// since it now has a visible child) — the abandon only fires when
    /// `commit` isn't a descendant of the old wc commit (e.g. `jj new
    /// <unrelated-rev>`/`jj edit <sibling>`), leaving the old one an
    /// orphaned, empty, undescribed head. When the abandon *does* fire, it
    /// registers a rewrite like any other, so `rebase_descendants()` is
    /// still required before `commit()` even though the abandoned commit
    /// had no descendants of its own to rebase — same
    /// assert-non-empty-`parent_mapping` requirement documented on
    /// `checkout::snapshot()`.
    fn edit(&self, workspace_name: String, commit: &PyCommit) -> PyResult<()> {
        use jj_lib::ref_name::WorkspaceNameBuf;
        let name = WorkspaceNameBuf::from(workspace_name.as_str());
        with_mut_repo(self, |mut_repo| {
            pollster::block_on(mut_repo.edit(name, &commit.inner)).map_err(map_transaction_err)
        })
    }

    /// Create a new working-copy commit *on top of* `commit` (carrying its
    /// tree) and edit that, returning the new commit.
    ///
    /// This is `jj_lib`'s `MutableRepo::check_out`, and it differs from
    /// `edit()`: `edit()` moves the working copy onto `commit` itself,
    /// while this leaves `commit` untouched and puts a fresh child in
    /// front of it. `jj bisect run` uses this one, so each candidate is
    /// tested without rewriting the revision being tested.
    fn check_out(&self, workspace_name: String, commit: &PyCommit) -> PyResult<PyCommit> {
        use jj_lib::ref_name::WorkspaceNameBuf;
        let name = WorkspaceNameBuf::from(workspace_name.as_str());
        let new_commit = with_mut_repo(self, |mut_repo| {
            pollster::block_on(mut_repo.check_out(name, &commit.inner))
                .map_err(map_transaction_err)
        })?;
        Ok(PyCommit {
            inner: new_commit,
            _repo: None,
        })
    }

    /// Point a local bookmark at a commit, creating it if it didn't exist.
    /// Overwrites any existing (possibly conflicted) target.
    fn set_bookmark(&self, name: &str, commit_id: &PyCommitId) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            mut_repo.set_local_bookmark_target(
                RefName::new(name),
                RefTarget::normal(commit_id.0.clone()),
            );
            Ok(())
        })
    }

    /// Delete a local bookmark. No-op if it didn't exist.
    fn delete_bookmark(&self, name: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            mut_repo.set_local_bookmark_target(RefName::new(name), RefTarget::absent());
            Ok(())
        })
    }

    /// The named local bookmark as currently seen within this transaction,
    /// or `None` if it doesn't exist.
    fn get_bookmark(&self, name: &str) -> PyResult<Option<PyBookmark>> {
        with_mut_repo(self, |mut_repo| {
            let ref_name = RefName::new(name);
            let target = mut_repo.get_local_bookmark(ref_name);
            Ok(if target.is_absent() {
                None
            } else {
                Some(PyBookmark::from_target(ref_name, &target))
            })
        })
    }

    /// All local bookmarks as currently seen within this transaction.
    fn bookmarks(&self) -> PyResult<Vec<PyBookmark>> {
        with_mut_repo(self, |mut_repo| {
            Ok(mut_repo
                .view()
                .local_bookmarks()
                .map(|(name, target)| PyBookmark::from_target(name, target))
                .collect())
        })
    }

    /// Point a local tag at a commit, creating it if it didn't exist.
    /// Overwrites any existing (possibly conflicted) target.
    fn set_tag(&self, name: &str, commit_id: &PyCommitId) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            mut_repo
                .set_local_tag_target(RefName::new(name), RefTarget::normal(commit_id.0.clone()));
            Ok(())
        })
    }

    /// Delete a local tag. No-op if it didn't exist.
    fn delete_tag(&self, name: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            mut_repo.set_local_tag_target(RefName::new(name), RefTarget::absent());
            Ok(())
        })
    }

    /// The named local tag as currently seen within this transaction, or
    /// `None` if it doesn't exist.
    fn get_tag(&self, name: &str) -> PyResult<Option<crate::tag::PyTag>> {
        with_mut_repo(self, |mut_repo| {
            let ref_name = RefName::new(name);
            let target = mut_repo.get_local_tag(ref_name);
            Ok(if target.is_absent() {
                None
            } else {
                Some(crate::tag::PyTag::from_target(ref_name, &target))
            })
        })
    }

    /// All local tags as currently seen within this transaction.
    fn tags(&self) -> PyResult<Vec<crate::tag::PyTag>> {
        with_mut_repo(self, |mut_repo| {
            Ok(mut_repo
                .view()
                .local_tags()
                .map(|(name, target)| crate::tag::PyTag::from_target(name, target))
                .collect())
        })
    }

    /// Rebase descendants after rewrites. Call this before `commit()`.
    ///
    /// `delete_abandoned_bookmarks` controls what happens to bookmarks
    /// pointing at *abandoned* commits (only recorded via
    /// `abandon_commit()`/`edit()`-style operations): `false` (the
    /// jj_lib default) moves them to the abandoned commit's parents,
    /// `true` deletes them -- matching the real CLI's `jj abandon`
    /// default (`--retain-bookmarks` opts back into moving). Rewritten
    /// (non-abandoned) commits always track their successors regardless.
    #[pyo3(signature = (delete_abandoned_bookmarks=false))]
    fn rebase_descendants(&self, delete_abandoned_bookmarks: bool) -> PyResult<usize> {
        with_mut_repo(self, |mut_repo| {
            let options = jj_lib::rewrite::RebaseOptions {
                rewrite_refs: jj_lib::rewrite::RewriteRefsOptions {
                    delete_abandoned_bookmarks,
                },
                ..Default::default()
            };
            let num_rebased = std::cell::Cell::new(0usize);
            pollster::block_on(mut_repo.rebase_descendants_with_options(
                &jj_lib::revset::RevsetExpression::none(),
                &options,
                |_, _| num_rebased.set(num_rebased.get() + 1),
            ))
            .map_err(map_transaction_err)?;
            Ok(num_rebased.into_inner())
        })
    }

    /// `jj git import` equivalent: reflect changes from the underlying
    /// (colocated) Git repo into this transaction's view.
    fn git_import_refs(&self) -> PyResult<Py<PyAny>> {
        with_mut_repo(self, crate::git::import_refs)
    }

    /// `jj git export` equivalent: reflect bookmark/tag changes made in this
    /// transaction into the underlying (colocated) Git repo's refs.
    fn git_export_refs(&self) -> PyResult<Py<PyAny>> {
        with_mut_repo(self, crate::git::export_refs)
    }

    /// Names of all configured Git remotes.
    fn git_remotes(&self) -> PyResult<Vec<String>> {
        with_mut_repo(self, |mut_repo| crate::git::list_remotes(mut_repo.store()))
    }

    /// `jj git remote add` equivalent.
    fn git_add_remote(&self, name: &str, url: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| crate::git::add_remote(mut_repo, name, url))
    }

    /// `jj git remote remove` equivalent.
    fn git_remove_remote(&self, name: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| crate::git::remove_remote(mut_repo, name))
    }

    /// `jj git remote rename` equivalent.
    fn git_rename_remote(&self, old_name: &str, new_name: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::git::rename_remote(mut_repo, old_name, new_name)
        })
    }

    /// `jj git remote set-url` equivalent.
    #[pyo3(signature = (name, url=None, push_url=None))]
    fn git_set_remote_urls(
        &self,
        name: &str,
        url: Option<&str>,
        push_url: Option<&str>,
    ) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::git::set_remote_urls(mut_repo.store(), name, url, push_url)
        })
    }

    /// `jj bookmark track` equivalent for a remote bookmark.
    fn git_track_remote_bookmark(&self, remote: &str, bookmark: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::git::track_remote_bookmark(mut_repo, remote, bookmark)
        })
    }

    /// `jj bookmark untrack` equivalent for a remote bookmark.
    fn git_untrack_remote_bookmark(&self, remote: &str, bookmark: &str) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::git::untrack_remote_bookmark(mut_repo, remote, bookmark);
            Ok(())
        })
    }

    /// `jj git fetch` equivalent: fetches the given bookmark names from
    /// `remote` (as a `git fetch` subprocess) and imports the result.
    fn git_fetch(
        &self,
        settings: &PyUserSettings,
        remote: &str,
        bookmark_names: Vec<String>,
    ) -> PyResult<Py<PyAny>> {
        with_mut_repo(self, |mut_repo| {
            crate::git::fetch(mut_repo, settings, remote, bookmark_names)
        })
    }

    /// Fetches *all* branches and tags from `remote` (unlike `git_fetch()`,
    /// which only fetches the named bookmarks and no tags) -- the fetch
    /// step behind `Workspace.clone_git()`. Returns the same stats shape
    /// as `git_fetch()`, plus `default_branch` (`Optional[str]`, the
    /// remote's default branch name if discoverable).
    fn git_fetch_all(&self, settings: &PyUserSettings, remote: &str) -> PyResult<Py<PyAny>> {
        with_mut_repo(self, |mut_repo| {
            crate::git::fetch_all(mut_repo, settings, remote)
        })
    }

    /// `jj squash` equivalent: moves `source`'s changes (optionally
    /// restricted to whole `paths`, and/or to specific `hunks` -- a
    /// `{path: [hunk_index, ...]}` map, indices from
    /// `pyjj_bindings.diff_hunks(before, after)`) into `destination`.
    /// Returns `None` if there's nothing to squash. See
    /// `pyjj_bindings.rewrite.squash` docs.
    #[pyo3(signature = (source, destination, paths=None, hunks=None, keep_emptied=false))]
    fn squash(
        &self,
        source: &PyCommit,
        destination: &PyCommit,
        paths: Option<Vec<String>>,
        hunks: Option<std::collections::HashMap<String, Vec<usize>>>,
        keep_emptied: bool,
    ) -> PyResult<Option<PyCommitBuilder>> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::squash(mut_repo, source, destination, paths, hunks, keep_emptied)
        })
    }

    /// `jj split` equivalent, first half: a `CommitBuilder` for the changes
    /// matched by whole `paths` and/or specific `hunks` (a
    /// `{path: [hunk_index, ...]}` map, indices from
    /// `pyjj_bindings.diff_hunks(before, after)`). Write this, then pass
    /// the result to `split_remainder()`.
    #[pyo3(signature = (target, paths=None, hunks=None))]
    fn split_selected(
        &self,
        target: &PyCommit,
        paths: Option<Vec<String>>,
        hunks: Option<std::collections::HashMap<String, Vec<usize>>>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::split_selected(mut_repo, target, paths, hunks)
        })
    }

    /// `split_selected()` for diff-editor flows: `selections` maps changed
    /// paths to post-editing content (`None` = dropped). The first half's
    /// tree is the parent tree overlaid with exactly these contents.
    fn split_selected_edited(
        &self,
        target: &PyCommit,
        selections: std::collections::HashMap<String, Option<Vec<u8>>>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::split_selected_edited(mut_repo, target, selections)
        })
    }

    /// Rewrite `commit` with per-path content overrides on top of its own
    /// tree (`diffedit`'s model; `None` removes a path).
    fn edit_commit_tree(
        &self,
        commit: &PyCommit,
        selections: std::collections::HashMap<String, Option<Vec<u8>>>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::edit_commit_tree(mut_repo, commit, selections)
        })
    }

    /// `jj split` equivalent, second half: a `CommitBuilder` for `target`'s
    /// remaining changes, as a child of `first`.
    fn split_remainder(&self, target: &PyCommit, first: &PyCommit) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::split_remainder(mut_repo, target, first)
        })
    }

    /// `jj split --parallel` equivalent, second half: the remaining
    /// changes as a *sibling* of `first` rather than its child.
    fn split_remainder_parallel(
        &self,
        target: &PyCommit,
        first: &PyCommit,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::split_remainder_parallel(mut_repo, target, first)
        })
    }

    /// Applies edited conflict-marker text back onto `commit`'s tree at
    /// `path`, returning a `CommitBuilder` for the rewritten commit. See
    /// `Commit.materialize_conflict()` and
    /// `pyjj_bindings.conflicts.resolve_conflict` docs.
    fn resolve_conflict(
        &self,
        commit: &PyCommit,
        path: &str,
        content: &[u8],
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::conflicts::resolve_conflict(mut_repo, commit, path, content)
        })
    }

    /// Multi-path variant of `resolve_conflict`: resolves every entry of
    /// `{path: edited marker text}` in ONE tree rewrite (single
    /// committer-timestamp bump), like real `jj resolve` applying all its
    /// merge-tool results to one tree. Raises `JjError` if any path isn't
    /// a resolvable file conflict.
    fn resolve_conflicts(
        &self,
        commit: &PyCommit,
        selections: std::collections::HashMap<String, Vec<u8>>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::conflicts::resolve_conflicts(mut_repo, commit, selections)
        })
    }

    /// Pick one side of each conflicted file, like `jj resolve --tool
    /// :ours` (side 0) / `:theirs` (side 1). The chosen side's `FileId`
    /// is kept verbatim. Raises `JjError` unless every path is a
    /// resolvable two-sided plain-file conflict.
    fn pick_conflict_sides(
        &self,
        commit: &PyCommit,
        paths: Vec<String>,
        side: usize,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::conflicts::pick_conflict_sides(mut_repo, commit, paths, side)
        })
    }

    /// `jj revert -r <commit> -d <new_parent_ids>` equivalent: reverses
    /// `commit`'s own changes and applies that reverse on top of
    /// `new_parent_ids`. Returns a `CommitBuilder` -- caller sets a
    /// description and `write()`s it. See `pyjj_bindings.revert.revert_commit`
    /// docs for chaining multiple reverts and for descendant-rebasing notes.
    fn revert_commit(
        &self,
        commit: &PyCommit,
        new_parent_ids: Vec<PyCommitId>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::revert::revert_commit(mut_repo, commit, new_parent_ids)
        })
    }

    /// `jj duplicate` equivalent: creates copies of `commits` (same tree/
    /// description/author, fresh change ids) onto their own original
    /// parents, leaving the originals untouched. See
    /// `pyjj_bindings.rewrite.duplicate` docs for the ordering requirement
    /// when duplicating more than one commit at once. Already written and
    /// committed within this transaction -- no `CommitBuilder` step needed.
    fn duplicate(&self, commits: Vec<PyCommit>) -> PyResult<Vec<PyCommit>> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::duplicate(mut_repo, commits)
        })
    }

    /// `jj file chmod (executable|normal) <path>` equivalent: flips the
    /// executable bit of the regular file at `path` in `commit`'s tree.
    /// Returns a `CommitBuilder` -- caller `write()`s it and calls
    /// `rebase_descendants()` if `commit` has descendants.
    fn set_executable(
        &self,
        commit: &PyCommit,
        path: &str,
        executable: bool,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::set_executable(mut_repo, commit, path, executable)
        })
    }


    /// `jj restore [paths] --from <src> --into <dest>` equivalent. Overwrites
    /// `paths` (or everything) in `into_commit`'s tree with content from
    /// `from_commit`, leaving `from_commit` untouched. Returns a
    /// `CommitBuilder` -- caller `write()`s it and calls
    /// `rebase_descendants()` if `into_commit` has descendants.
    #[pyo3(signature = (from_commit, into_commit, paths=None))]
    fn restore(
        &self,
        from_commit: &PyCommit,
        into_commit: &PyCommit,
        paths: Option<Vec<String>>,
    ) -> PyResult<PyCommitBuilder> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::restore(mut_repo, from_commit, into_commit, paths)
        })
    }

    /// `jj absorb` equivalent: splits `source_commit`'s changes and moves
    /// each hunk into the closest ancestor (among `destinations`, a revset
    /// expression defaulting to `"mutable()"` like the CLI) where those
    /// lines were last modified. `source_commit` is abandoned if
    /// everything was absorbed and it has no description. Returns an
    /// `AbsorbStats` (`.source`, `.destinations`, `.num_rebased`).
    /// `rebase_descendants()` is still required before `commit()`, same as
    /// every other rewrite here -- `MutableRepo::transform_descendants`
    /// (which this wraps) already rebases the specific commits it visits
    /// internally, but still leaves a pending-rewrite record that
    /// `Transaction::commit()` asserts must be cleared first (verified
    /// empirically: omitting it panics with "Descendants have not been
    /// rebased after the last rewrites", same assertion every other
    /// rewrite-registering call here is subject to).
    #[pyo3(signature = (settings, source_commit, destinations=None, paths=None))]
    fn absorb(
        &self,
        settings: &PyUserSettings,
        source_commit: &PyCommit,
        destinations: Option<&str>,
        paths: Option<Vec<String>>,
    ) -> PyResult<crate::absorb::PyAbsorbStats> {
        with_mut_repo(self, |mut_repo| {
            crate::absorb::absorb(
                self,
                mut_repo,
                settings,
                source_commit,
                destinations.unwrap_or("mutable()"),
                paths,
            )
        })
    }

    /// `jj fix`'s enumeration half: resolves `revset` (default
    /// `"reachable(@, mutable())"`, jj's own `revsets.fix` default) and its
    /// descendants, and returns the deduplicated `FileToFix`s (path +
    /// current content) that might need fixing, restricted to `paths` if
    /// given. Doesn't itself change anything -- run each file's `content`
    /// through whatever external tool you want in Python (e.g. via
    /// `subprocess`), then pass the results to `fix_apply()`. This
    /// data-in/data-out split is the same idiom `diff_hunks()` +
    /// `squash(hunks=...)` uses for interactive hunk selection, and
    /// `Commit.materialize_conflict()` + `Transaction.resolve_conflict()`
    /// use for external merge tools -- none of them need a Python callback
    /// into a Rust trait; jj_lib's `FileFixer` trait exists so the *CLI* can
    /// plug in `ParallelFileFixer` (which spawns formatter/linter
    /// subprocesses itself, see `cli/src/commands/fix.rs`), but the trait
    /// itself is satisfied here by a plain Rust closure over
    /// already-computed data, not by calling back into Python.
    #[pyo3(signature = (settings, revset=None, paths=None, include_unchanged_files=false))]
    fn fix_enumerate(
        &self,
        settings: &PyUserSettings,
        revset: Option<&str>,
        paths: Option<Vec<String>>,
        include_unchanged_files: bool,
    ) -> PyResult<Vec<crate::fix::PyFileToFix>> {
        with_mut_repo(self, |mut_repo| {
            crate::fix::fix_enumerate(self, mut_repo, settings, revset, paths, include_unchanged_files)
        })
    }

    /// `jj fix`'s apply half: same `revset`/`paths` selection as
    /// `fix_enumerate()`, but applies a `{FileToFix.key: new_content}`
    /// mapping instead of recomputing anything -- rewriting each affected
    /// commit and propagating the fix to its descendants so it isn't lost,
    /// same rule real `jj fix` follows. A file whose key is missing from
    /// `fixes` is left unchanged. Still needs `rebase_descendants()` before
    /// `commit()`, same as every other rewrite here.
    #[pyo3(signature = (settings, fixes, revset=None, paths=None, include_unchanged_files=false))]
    fn fix_apply(
        &self,
        settings: &PyUserSettings,
        fixes: std::collections::HashMap<String, Vec<u8>>,
        revset: Option<&str>,
        paths: Option<Vec<String>>,
        include_unchanged_files: bool,
    ) -> PyResult<crate::fix::PyFixSummary> {
        with_mut_repo(self, |mut_repo| {
            crate::fix::fix_apply(self, mut_repo, settings, revset, paths, fixes, include_unchanged_files)
        })
    }

    /// `jj abandon <rev>` equivalent: removes `commit` from history. Any
    /// descendants (and a working-copy commit pointing at it) get rebased
    /// onto its parents -- but only once `rebase_descendants()` is called
    /// afterward, same as every other rewrite here.
    fn abandon_commit(&self, commit: &PyCommit) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::abandon(mut_repo, commit);
            Ok(())
        })
    }

    /// `jj rebase -r <rev> -d <dest>` equivalent for a single commit --
    /// `commit`'s own descendants are *not* moved along; call
    /// `rebase_descendants()` afterward for that (matching every other
    /// rewrite in this API). Already written -- no `CommitBuilder` step.
    fn rebase(&self, commit: &PyCommit, new_parents: Vec<PyCommitId>) -> PyResult<PyCommit> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::rebase(mut_repo, commit, new_parents)
        })
    }

    /// `jj rebase` equivalent covering every destination mode (`-r`/`-s`,
    /// `-d`/`-A`/`-B`) in one call. See `pyjj_bindings.rewrite.move_commits`
    /// docs for exactly what each argument means and the mutual-exclusion
    /// rule between `target_commit_ids`/`target_root_ids`. Already rebases
    /// the target's descendants -- call `rebase_descendants()` afterward
    /// only for other pending rewrites in this transaction, same as
    /// everywhere else in this API.
    fn move_commits(
        &self,
        target_commit_ids: Vec<PyCommitId>,
        target_root_ids: Vec<PyCommitId>,
        new_parent_ids: Vec<PyCommitId>,
        new_child_ids: Vec<PyCommitId>,
    ) -> PyResult<crate::rewrite::PyMoveCommitsStats> {
        with_mut_repo(self, |mut_repo| {
            crate::rewrite::move_commits(
                mut_repo,
                target_commit_ids,
                target_root_ids,
                new_parent_ids,
                new_child_ids,
            )
        })
    }

    /// `jj op restore <target_op>` equivalent. `what` defaults to
    /// restoring everything (`["repo", "remote_tracking"]`); pass a subset
    /// to restore only part of the view. Does not commit -- call
    /// `.commit(description)` afterward.
    #[pyo3(signature = (target_op, what=None))]
    fn restore_operation(
        &self,
        target_op: &crate::operation::PyOperation,
        what: Option<Vec<String>>,
    ) -> PyResult<()> {
        with_mut_repo(self, |mut_repo| {
            crate::oplog::restore_operation(mut_repo, target_op, what)
        })
    }

    /// `jj undo` equivalent. Returns `(undone_op, restored_to_op,
    /// description)` -- pass `description` unchanged to `.commit()`
    /// afterward (it's not just a message, it's how future `undo()`/
    /// `redo()` calls recognize the undo-stack -- see the Rust docs on
    /// `pyjj_bindings.oplog.undo`). Does not commit on its own.
    fn undo(
        &self,
    ) -> PyResult<(
        crate::operation::PyOperation,
        crate::operation::PyOperation,
        String,
    )> {
        with_mut_repo(self, crate::oplog::undo)
    }

    /// `jj redo` equivalent, the complement of `undo()`. Same return shape
    /// and description-handling as `undo()`.
    fn redo(
        &self,
    ) -> PyResult<(
        crate::operation::PyOperation,
        crate::operation::PyOperation,
        String,
    )> {
        with_mut_repo(self, crate::oplog::redo)
    }

    /// `jj git push -b <bookmark>` equivalent.
    fn git_push_bookmark(
        &self,
        settings: &PyUserSettings,
        remote: &str,
        bookmark: &str,
    ) -> PyResult<Py<PyAny>> {
        with_mut_repo(self, |mut_repo| {
            crate::git::push_bookmark(mut_repo, settings, remote, bookmark)
        })
    }

    /// Commit this transaction and publish the operation.
    fn commit(&self, description: String) -> PyResult<PyReadonlyRepo> {
        let tx = self.inner.borrow_mut().take().ok_or_else(|| {
            crate::errors::TransactionError::new_err("Transaction already committed")
        })?;
        let repo = pollster::block_on(tx.commit(description)).map_err(map_transaction_err)?;
        Ok(PyReadonlyRepo {
            inner: repo,
            workspace_root: self.workspace_root.clone(),
            workspace_name: self.workspace_name.clone(),
        })
    }

    fn __repr__(&self) -> String {
        if self.inner.borrow().is_some() {
            "Transaction(open)".into()
        } else {
            "Transaction(consumed)".into()
        }
    }
}

// ── CommitBuilder ───────────────────────────────────────────────────────────

/// Builder for creating or rewriting commits.
///
/// Obtained from `Transaction.new_commit()` or `Transaction.rewrite_commit()`.
/// Call `write()` to finalize, or `abandon()` to abandon the old commit.
#[pyclass(name = "CommitBuilder", unsendable)]
pub struct PyCommitBuilder {
    inner: Option<CommitBuilder<'static>>,
}

impl PyCommitBuilder {
    pub(crate) fn from_rust(builder: CommitBuilder<'_>) -> Self {
        // SAFETY: The Python GIL and object lifetimes ensure the MutableRepo
        // (via Transaction) outlives this builder.
        let static_builder: CommitBuilder<'static> = unsafe { std::mem::transmute(builder) };
        Self {
            inner: Some(static_builder),
        }
    }
}

/// Takes the inner builder, or a clean [`TransactionError`](crate::errors::TransactionError)
/// if it was already consumed by a previous `write()`/`abandon()` call —
/// instead of panicking, which would tear down the whole Python process.
fn take_inner(inner: &mut Option<CommitBuilder<'static>>) -> PyResult<CommitBuilder<'static>> {
    inner
        .take()
        .ok_or_else(|| crate::errors::TransactionError::new_err("CommitBuilder already consumed"))
}

#[pymethods]
impl PyCommitBuilder {
    fn set_description(
        mut slf: PyRefMut<'_, Self>,
        description: String,
    ) -> PyResult<PyRefMut<'_, Self>> {
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_description(description));
        Ok(slf)
    }

    fn set_author(
        mut slf: PyRefMut<'_, Self>,
        author: PySignature,
    ) -> PyResult<PyRefMut<'_, Self>> {
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_author(author.0));
        Ok(slf)
    }

    fn set_committer(
        mut slf: PyRefMut<'_, Self>,
        committer: PySignature,
    ) -> PyResult<PyRefMut<'_, Self>> {
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_committer(committer.0));
        Ok(slf)
    }

    fn set_parents(
        mut slf: PyRefMut<'_, Self>,
        parent_ids: Vec<PyCommitId>,
    ) -> PyResult<PyRefMut<'_, Self>> {
        let ids: Vec<CommitId> = parent_ids.into_iter().map(|p| p.0).collect();
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_parents(ids));
        Ok(slf)
    }

    fn set_change_id<'a>(
        mut slf: PyRefMut<'a, Self>,
        change_id: &'a PyChangeId,
    ) -> PyResult<PyRefMut<'a, Self>> {
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_change_id(change_id.0.clone()));
        Ok(slf)
    }

    /// Assigns a fresh, random change id instead of inheriting the source
    /// commit's (only meaningful when this builder came from
    /// `rewrite_commit()`/`split_remainder()`, which otherwise preserve it).
    fn generate_new_change_id(mut slf: PyRefMut<'_, Self>) -> PyResult<PyRefMut<'_, Self>> {
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.generate_new_change_id());
        Ok(slf)
    }

    fn set_sign_behavior<'a>(
        mut slf: PyRefMut<'a, Self>,
        behavior: &'a str,
    ) -> Result<PyRefMut<'a, Self>, PyErr> {
        use jj_lib::signing::SignBehavior;
        let behavior = match behavior {
            "drop" => SignBehavior::Drop,
            "keep" => SignBehavior::Keep,
            "own" => SignBehavior::Own,
            "force" => SignBehavior::Force,
            _ => {
                return Err(crate::errors::JjError::new_err(format!(
                    "unknown sign behavior: {behavior}"
                )));
            }
        };
        let builder = take_inner(&mut slf.inner)?;
        slf.inner = Some(builder.set_sign_behavior(behavior));
        Ok(slf)
    }

    /// Write this commit to the repository. Returns the new [`Commit`].
    fn write(mut slf: PyRefMut<'_, Self>, repo: &PyReadonlyRepo) -> PyResult<PyCommit> {
        let builder = take_inner(&mut slf.inner)?;
        let commit = pollster::block_on(builder.write()).map_err(map_backend_err)?;
        Ok(PyCommit {
            inner: commit,
            _repo: Some(repo.inner.clone()),
        })
    }

    /// Abandon the source commit instead of writing a new one.
    fn abandon(mut slf: PyRefMut<'_, Self>) {
        if let Some(builder) = slf.inner.take() {
            builder.abandon();
        }
    }

    fn __repr__(&self) -> String {
        if let Some(ref b) = self.inner {
            format!("CommitBuilder({})", b.change_id().reverse_hex())
        } else {
            "CommitBuilder(consumed)".into()
        }
    }
}
