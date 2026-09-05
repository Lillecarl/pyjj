use std::sync::Arc;

use pyo3::prelude::*;

use jj_lib::commit::Commit;
use jj_lib::object_id::ObjectId as _;

use crate::errors::map_py_err;
use crate::ids::{PyChangeId, PyCommitId, PySignature};

/// The result of verifying a commit's cryptographic signature
/// (`Commit.verification`) -- `None` if the commit isn't signed at all
/// (same as `is_signed` being `False`). `status` is one of `"good"`
/// (valid signature, key recognized), `"unknown"` (valid signature, but
/// the key couldn't be verified/recognized), or `"bad"` (signature doesn't
/// match the signed data). `key`/`display` are backend-provided extra
/// metadata (for the `ssh`/`gpg` backends: the key fingerprint / formatted
/// user id) -- either may be `None` if the backend didn't supply it.
#[pyclass(name = "Verification", frozen, get_all)]
pub struct PyVerification {
    status: String,
    key: Option<String>,
    display: Option<String>,
}

impl From<jj_lib::signing::Verification> for PyVerification {
    fn from(v: jj_lib::signing::Verification) -> Self {
        Self {
            status: v.status.to_string(),
            key: v.key,
            display: v.display,
        }
    }
}

/// An immutable commit object.
#[pyclass(name = "Commit", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyCommit {
    pub(crate) inner: Commit,
    // We hold an Arc to the repo so the commit's store stays alive.
    #[allow(dead_code)]
    pub(crate) _repo: Option<Arc<jj_lib::repo::ReadonlyRepo>>,
}

#[pymethods]
impl PyCommit {
    #[getter]
    fn id(&self) -> PyCommitId {
        PyCommitId(self.inner.id().clone())
    }

    #[getter]
    fn change_id(&self) -> PyChangeId {
        PyChangeId(self.inner.change_id().clone())
    }

    #[getter]
    fn description(&self) -> &str {
        self.inner.description()
    }

    #[getter]
    fn author(&self) -> PySignature {
        self.inner.author().clone().into()
    }

    #[getter]
    fn committer(&self) -> PySignature {
        self.inner.committer().clone().into()
    }

    #[getter]
    fn parent_ids(&self) -> Vec<PyCommitId> {
        self.inner
            .parent_ids()
            .iter()
            .map(PyCommitId::from)
            .collect()
    }

    #[getter]
    fn has_conflict(&self) -> bool {
        self.inner.has_conflict()
    }

    #[getter]
    fn is_signed(&self) -> bool {
        self.inner.is_signed()
    }

    /// The full signature verification (status/key/display), or `None` if
    /// unsigned. Slower than `is_signed` (actually invokes the signing
    /// backend to verify, though the result is cached) but tells you
    /// *whether the signature is actually good*, not just present --
    /// `is_signed` alone can't distinguish a valid signature from a bad or
    /// unrecognized one.
    #[getter]
    fn verification(&self) -> PyResult<Option<PyVerification>> {
        Ok(self
            .inner
            .verification()
            .map_err(map_py_err)?
            .map(Into::into))
    }

    /// Every conflicted path in this commit's tree, as `(path, sides,
    /// adds, objects)`. See `conflicts::conflicted_paths`.
    fn conflicted_paths(&self) -> PyResult<Vec<(String, usize, usize, Vec<String>)>> {
        crate::conflicts::conflicted_paths(self)
    }

    /// This commit's changes against its parents *merged*, which is what
    /// `jj status` shows.
    ///
    /// Diffing against the first parent alone reports a merge commit as
    /// changing everything the other parents contributed. jj compares
    /// against the merged parent tree, so a merge that resolves nothing
    /// reports no changes at all.
    #[pyo3(signature = (repo, paths=None))]
    fn diff_from_parents(
        &self,
        repo: &PyReadonlyRepo,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        crate::tree::diff_from_parents(self, repo, paths)
    }

    /// Whether this commit is no longer reachable from any visible head.
    ///
    /// A rewrite leaves its earlier versions hidden rather than deleting
    /// them, which is what `jj evolog` walks. jj marks such a commit
    /// `(hidden)` wherever it prints one.
    fn is_hidden(&self, repo: &PyReadonlyRepo) -> PyResult<bool> {
        self.inner
            .is_hidden(repo.inner.as_ref())
            .map_err(crate::errors::map_py_err)
    }

    /// Whether more than one visible commit shares this commit's change
    /// id.
    ///
    /// A rewrite that lands twice, or a `duplicate` that keeps the
    /// change id, leaves the change addressing several commits at once.
    /// jj marks every one of them `(divergent)`.
    fn is_divergent(&self, repo: &PyReadonlyRepo) -> PyResult<bool> {
        use jj_lib::repo::Repo as _;

        let targets = repo
            .inner
            .resolve_change_id(self.inner.change_id())
            .map_err(crate::errors::map_py_err)?;
        Ok(targets.is_some_and(|targets| targets.is_divergent()))
    }

    /// This commit's position among the commits sharing its change id,
    /// or `None` if the change does not resolve.
    ///
    /// jj writes it after the change id as `/1`, `/2` and so on, and
    /// that spelling is a revset: it is how a reader addresses an
    /// earlier version of a change. Position 0 is the visible one, and
    /// jj prints no offset for it.
    fn change_offset(&self, repo: &PyReadonlyRepo) -> PyResult<Option<usize>> {
        use jj_lib::repo::Repo as _;

        let targets = repo
            .inner
            .resolve_change_id(self.inner.change_id())
            .map_err(crate::errors::map_py_err)?;
        Ok(targets.and_then(|targets| targets.find_offset(self.inner.id())))
    }

    /// Whether this commit has no changes compared to its parent(s). Returns
    /// `false` if there are no parent commits to compare against (the root).
    fn is_empty(&self, repo: &PyReadonlyRepo) -> bool {
        pollster::block_on(self.inner.is_empty(repo.inner.as_ref())).unwrap_or(false)
    }

    /// Async sibling of `is_empty()`. Runs on tokio's blocking thread pool
    /// (see the `aio` module docs) rather than on the calling thread.
    fn is_empty_async<'py>(
        &self,
        py: Python<'py>,
        repo: PyReadonlyRepo,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.inner.clone();
        crate::aio::spawn_blocking_py(py, move || {
            Ok(pollster::block_on(commit.is_empty(repo.inner.as_ref())).unwrap_or(false))
        })
    }

    /// Whether this commit is discardable (empty + no description).
    fn is_discardable(&self, repo: &PyReadonlyRepo) -> bool {
        pollster::block_on(self.inner.is_discardable(repo.inner.as_ref())).unwrap_or(false)
    }

    /// Async sibling of `is_discardable()`. Runs on tokio's blocking thread
    /// pool (see the `aio` module docs) rather than on the calling thread.
    fn is_discardable_async<'py>(
        &self,
        py: Python<'py>,
        repo: PyReadonlyRepo,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.inner.clone();
        crate::aio::spawn_blocking_py(py, move || {
            Ok(pollster::block_on(commit.is_discardable(repo.inner.as_ref())).unwrap_or(false))
        })
    }

    /// Path-level diff of this commit's tree against `other`'s tree. No
    /// copy/rename detection — a rename shows up as a "removed" + "added"
    /// pair. Use `diff_with_copies()` for copy/rename-aware diffing.
    ///
    /// `paths`, if given, restricts the diff to those repo-relative paths
    /// (and anything under them) — like `jj diff <path>...`.
    #[pyo3(signature = (other, paths=None))]
    fn diff(
        &self,
        other: &Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        crate::tree::diff_commits(self, other, paths)
    }

    /// `jj diff --stat`'s numbers: lines added and removed at each
    /// changed path, plus the byte delta.
    ///
    /// Unlike `diff()`, this reads file content, so it costs more. A
    /// binary file reports `None` for both counts, decided the way jj
    /// and git decide it -- a NUL byte in the first 8000 bytes.
    ///
    /// `compare` is how two lines are compared, as for
    /// `pyjj.content_hunks()`: jj's `-w` and `-b` change these counts,
    /// because they change which lines it calls the same.
    #[pyo3(signature = (other, settings, paths=None, compare="exact"))]
    fn diff_stats(
        &self,
        other: &Self,
        settings: &crate::settings::PyUserSettings,
        paths: Option<Vec<String>>,
        compare: &str,
    ) -> PyResult<Vec<crate::tree::PyDiffStat>> {
        crate::tree::diff_stats(self, other, settings, paths, compare)
    }

    /// The per-file halves of `jj diff --git`: mode, abbreviated hash and
    /// materialized content for both sides of every changed path.
    ///
    /// Pair it with `pyjj.unified_hunks()` to format a git-style diff.
    /// What this settles is the part that has to agree with jj; the
    /// formatting is the caller's.
    #[pyo3(signature = (other, settings, paths=None, copies=true))]
    fn git_diff(
        &self,
        other: &Self,
        settings: &crate::settings::PyUserSettings,
        paths: Option<Vec<String>>,
        copies: bool,
    ) -> PyResult<Vec<crate::tree::PyGitDiffFile>> {
        crate::tree::git_diff_files(self, other, settings, paths, copies)
    }

    /// Async sibling of `diff()`. Runs on tokio's blocking thread pool (see
    /// the `aio` module docs) rather than on the calling thread.
    #[pyo3(signature = (other, paths=None))]
    fn diff_async<'py>(
        &self,
        py: Python<'py>,
        other: Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let from = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::tree::diff_commits(&from, &other, paths))
    }

    /// Like `diff()`, but detects copies and renames (backend-dependent —
    /// content-similarity-based for the git backend). See
    /// `diff_commits_with_copies` for details.
    #[pyo3(signature = (other, paths=None))]
    fn diff_with_copies(
        &self,
        other: &Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        crate::tree::diff_commits_with_copies(self, other, paths)
    }

    /// Async sibling of `diff_with_copies()`. Runs on tokio's blocking
    /// thread pool (see the `aio` module docs) rather than on the calling
    /// thread.
    #[pyo3(signature = (other, paths=None))]
    fn diff_with_copies_async<'py>(
        &self,
        py: Python<'py>,
        other: Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let from = self.clone();
        crate::aio::spawn_blocking_py(py, move || {
            crate::tree::diff_commits_with_copies(&from, &other, paths)
        })
    }

    /// The content of the file (or symlink target) at `path` in this
    /// commit's tree, as `bytes`.
    fn read_file(&self, path: &str) -> PyResult<Vec<u8>> {
        crate::file::read_file(self, path)
    }

    /// Async sibling of `read_file()`. Runs on tokio's blocking thread pool
    /// (see the `aio` module docs) rather than on the calling thread.
    fn read_file_async<'py>(&self, py: Python<'py>, path: String) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::file::read_file(&commit, &path))
    }

    /// Whether `path` names a regular/executable file or symlink in this
    /// commit's tree (`False` for directories, submodules, absent paths,
    /// and unresolved conflicts).
    fn file_exists(&self, path: &str) -> PyResult<bool> {
        crate::file::file_exists(self, path)
    }

    /// Async sibling of `file_exists()`. Runs on tokio's blocking thread
    /// pool (see the `aio` module docs) rather than on the calling thread.
    fn file_exists_async<'py>(&self, py: Python<'py>, path: String) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::file::file_exists(&commit, &path))
    }

    /// `jj file list [paths]` equivalent — every path in this commit's tree,
    /// optionally restricted to `paths` (see `pyjj_bindings.file.list_files`
    /// for the path-or-subtree matching rules).
    #[pyo3(signature = (paths=None))]
    fn list_files(&self, paths: Option<Vec<String>>) -> PyResult<Vec<String>> {
        crate::file::list_files(self, paths)
    }

    /// Async sibling of `list_files()`. Runs on tokio's blocking thread
    /// pool (see the `aio` module docs) rather than on the calling thread.
    #[pyo3(signature = (paths=None))]
    fn list_files_async<'py>(
        &self,
        py: Python<'py>,
        paths: Option<Vec<String>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::file::list_files(&commit, paths))
    }

    /// Whether `path` is a regular file with the executable bit set.
    /// `None` if `path` isn't a resolvable regular file (symlink,
    /// directory, submodule, absent, or conflicted) — see
    /// `pyjj_bindings.file.is_executable` for details.
    fn is_executable(&self, path: &str) -> PyResult<Option<bool>> {
        crate::file::is_executable(self, path)
    }

    /// Async sibling of `is_executable()`. Runs on tokio's blocking thread
    /// pool (see the `aio` module docs) rather than on the calling thread.
    fn is_executable_async<'py>(
        &self,
        py: Python<'py>,
        path: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::file::is_executable(&commit, &path))
    }

    /// Renders the conflict at `path` as conflict-marker text, the same
    /// way a real jj working copy would show it. Raises `JjError` if
    /// `path` isn't conflicted.
    fn materialize_conflict(
        &self,
        settings: &crate::settings::PyUserSettings,
        path: &str,
    ) -> PyResult<Vec<u8>> {
        crate::conflicts::materialize_conflict(self, settings, path)
    }

    /// Async sibling of `materialize_conflict()`. Runs on tokio's blocking
    /// thread pool (see the `aio` module docs) rather than on the calling
    /// thread.
    fn materialize_conflict_async<'py>(
        &self,
        py: Python<'py>,
        settings: &crate::settings::PyUserSettings,
        path: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        let settings = crate::settings::PyUserSettings(settings.0.clone());
        crate::aio::spawn_blocking_py(py, move || {
            crate::conflicts::materialize_conflict(&commit, &settings, &path)
        })
    }

    /// The raw sides of the file conflict at `path`, as an external 3-way
    /// merge tool receives them:
    /// `{"base": bytes, "left": bytes, "right": bytes, "executable": bool}`.
    /// `$base`/`$left`/`$right` in merge-args; base may be empty for
    /// add/add-style conflicts. Raises `JjError` unless `path` is a
    /// two-sided plain-file conflict (real `jj resolve` rejects anything
    /// else too).
    fn conflict_sides<'a>(
        &self,
        py: Python<'a>,
        path: &str,
    ) -> PyResult<Bound<'a, pyo3::types::PyDict>> {
        let (base, left, right, executable) =
            crate::conflicts::conflict_sides(self, path)?;
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item("base", base)?;
        dict.set_item("left", left)?;
        dict.set_item("right", right)?;
        dict.set_item("executable", executable)?;
        Ok(dict)
    }

    /// `jj file annotate <path>` equivalent (a.k.a. blame): who last touched
    /// each line of `path` as it appears in this commit.
    fn annotate(
        &self,
        repo: &PyReadonlyRepo,
        path: &str,
    ) -> PyResult<Vec<crate::annotate::PyAnnotationLine>> {
        crate::annotate::annotate(self, repo, path)
    }

    /// Async sibling of `annotate()`. Runs on tokio's blocking thread pool
    /// (see the `aio` module docs) rather than on the calling thread.
    fn annotate_async<'py>(
        &self,
        py: Python<'py>,
        repo: PyReadonlyRepo,
        path: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let commit = self.clone();
        crate::aio::spawn_blocking_py(py, move || crate::annotate::annotate(&commit, &repo, &path))
    }

    fn __repr__(&self) -> String {
        format!(
            "Commit({}, {})",
            self.inner.change_id().reverse_hex(),
            self.inner.id().hex()
        )
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.inner.id() == other.inner.id()
    }

    fn __hash__(&self) -> u64 {
        use std::hash::Hasher;
        let mut h = std::hash::DefaultHasher::new();
        std::hash::Hash::hash(self.inner.id(), &mut h);
        h.finish()
    }
}

// Forward declaration for circular reference
#[pyclass(name = "ReadonlyRepo", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyReadonlyRepo {
    pub(crate) inner: Arc<jj_lib::repo::ReadonlyRepo>,
    /// Needed to resolve workspace-relative revset symbols (e.g. `@`) and
    /// fileset paths. Carried alongside the repo rather than looked up from
    /// a `Workspace` object, since a repo can outlive/be detached from one
    /// (e.g. after `Transaction::commit()`).
    pub(crate) workspace_root: std::path::PathBuf,
    pub(crate) workspace_name: jj_lib::ref_name::WorkspaceNameBuf,
}
