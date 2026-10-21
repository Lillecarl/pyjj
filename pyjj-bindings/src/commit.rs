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
    fn conflicted_paths(&self, py: Python<'_>) -> PyResult<Vec<(String, usize, usize, Vec<String>)>> {
        py.detach(|| {
            crate::conflicts::conflicted_paths(self)
        })
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
        py: Python<'_>,
        repo: &PyReadonlyRepo,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        py.detach(|| {
            crate::tree::diff_from_parents(self, repo, paths)
        })
    }

    /// Whether this commit is no longer reachable from any visible head.
    ///
    /// A rewrite leaves its earlier versions hidden rather than deleting
    /// them, which is what `jj evolog` walks. jj marks such a commit
    /// `(hidden)` wherever it prints one.
    fn is_hidden(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<bool> {
        py.detach(|| {
            pollster::block_on(self.inner.is_hidden(repo.inner.as_ref()))
                .map_err(crate::errors::map_py_err)
        })
    }

    /// Whether more than one visible commit shares this commit's change
    /// id.
    ///
    /// A rewrite that lands twice, or a `duplicate` that keeps the
    /// change id, leaves the change addressing several commits at once.
    /// jj marks every one of them `(divergent)`.
    fn is_divergent(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<bool> {
        py.detach(|| {
            use jj_lib::repo::Repo as _;

            let targets = pollster::block_on(repo.inner.resolve_change_id(self.inner.change_id()))
                .map_err(crate::errors::map_py_err)?;
            Ok(targets.is_some_and(|targets| targets.is_divergent()))
        })
    }

    /// This commit's position among the commits sharing its change id,
    /// or `None` if the change does not resolve.
    ///
    /// jj writes it after the change id as `/1`, `/2` and so on, and
    /// that spelling is a revset: it is how a reader addresses an
    /// earlier version of a change. Position 0 is the visible one, and
    /// jj prints no offset for it.
    fn change_offset(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<Option<usize>> {
        py.detach(|| {
            use jj_lib::repo::Repo as _;

            let targets = pollster::block_on(repo.inner.resolve_change_id(self.inner.change_id()))
                .map_err(crate::errors::map_py_err)?;
            Ok(targets.and_then(|targets| targets.find_offset(self.inner.id())))
        })
    }

    /// Whether this commit has no changes compared to its parent(s).
    fn is_empty(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<bool> {
        py.detach(|| {
            pollster::block_on(self.inner.is_empty(repo.inner.as_ref())).map_err(map_py_err)
        })
    }

    /// Whether this commit is discardable (empty + no description).
    fn is_discardable(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<bool> {
        py.detach(|| {
            pollster::block_on(self.inner.is_discardable(repo.inner.as_ref())).map_err(map_py_err)
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
        py: Python<'_>,
        other: &Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        py.detach(|| {
            crate::tree::diff_commits(self, other, paths)
        })
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
        py: Python<'_>,
        other: &Self,
        settings: &crate::settings::PyUserSettings,
        paths: Option<Vec<String>>,
        compare: &str,
    ) -> PyResult<Vec<crate::tree::PyDiffStat>> {
        py.detach(|| {
            crate::tree::diff_stats(self, other, settings, paths, compare)
        })
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
        py: Python<'_>,
        other: &Self,
        settings: &crate::settings::PyUserSettings,
        paths: Option<Vec<String>>,
        copies: bool,
    ) -> PyResult<Vec<crate::tree::PyGitDiffFile>> {
        py.detach(|| {
            crate::tree::git_diff_files(self, other, settings, paths, copies)
        })
    }

    /// Like `diff()`, but detects copies and renames (backend-dependent —
    /// content-similarity-based for the git backend). See
    /// `diff_commits_with_copies` for details.
    #[pyo3(signature = (other, paths=None))]
    fn diff_with_copies(
        &self,
        py: Python<'_>,
        other: &Self,
        paths: Option<Vec<String>>,
    ) -> PyResult<Vec<crate::tree::PyDiffEntry>> {
        py.detach(|| {
            crate::tree::diff_commits_with_copies(self, other, paths)
        })
    }

    /// The content of the file (or symlink target) at `path` in this
    /// commit's tree, as `bytes`.
    fn read_file(&self, py: Python<'_>, path: &str) -> PyResult<Vec<u8>> {
        py.detach(|| {
            crate::file::read_file(self, path)
        })
    }

    /// The bytes at each of `paths` in this commit's *merged parent*
    /// tree, keyed by path, with `None` where the parent tree does not
    /// hold one. Pairs with `diff_from_parents()`, which names the
    /// paths.
    fn parent_contents(
        &self,
        py: Python<'_>,
        repo: &PyReadonlyRepo,
        paths: Vec<String>,
    ) -> PyResult<std::collections::HashMap<String, Option<Vec<u8>>>> {
        py.detach(|| {
            crate::file::parent_contents(self, repo, paths)
        })
    }

    /// Whether `path` names a regular/executable file or symlink in this
    /// commit's tree (`False` for directories, submodules, absent paths,
    /// and unresolved conflicts).
    fn file_exists(&self, py: Python<'_>, path: &str) -> PyResult<bool> {
        py.detach(|| {
            crate::file::file_exists(self, path)
        })
    }

    /// `jj file list [paths]` equivalent — every path in this commit's tree,
    /// optionally restricted to `paths` (see `pyjj_bindings.file.list_files`
    /// for the path-or-subtree matching rules).
    #[pyo3(signature = (paths=None))]
    fn list_files(&self, py: Python<'_>, paths: Option<Vec<String>>) -> PyResult<Vec<String>> {
        py.detach(|| {
            crate::file::list_files(self, paths)
        })
    }

    /// Whether `path` is a regular file with the executable bit set.
    /// `None` if `path` isn't a resolvable regular file (symlink,
    /// directory, submodule, absent, or conflicted) — see
    /// `pyjj_bindings.file.is_executable` for details.
    fn is_executable(&self, py: Python<'_>, path: &str) -> PyResult<Option<bool>> {
        py.detach(|| {
            crate::file::is_executable(self, path)
        })
    }

    /// The kind of tree entry at `path` — `"file"`, `"symlink"`, `"dir"`,
    /// `"submodule"`, `"absent"`, `"file-conflict"`, or
    /// `"other-conflict"` (see `pyjj_bindings.file.file_kind`).
    fn file_kind(&self, py: Python<'_>, path: &str) -> PyResult<String> {
        py.detach(|| {
            crate::file::file_kind(self, path)
        })
    }

    /// `jj`'s fileset matching against this commit's tree: `(matched,
    /// unmatched_explicit)` for `patterns` (see
    /// `pyjj_bindings.file.match_filesets`).
    fn match_filesets(
        &self,
        py: Python<'_>,
        settings: &crate::settings::PyUserSettings,
        workspace_root: &str,
        patterns: Vec<String>,
    ) -> PyResult<(Vec<String>, Vec<String>)> {
        py.detach(|| {
            crate::file::match_filesets(self, settings, workspace_root, patterns)
        })
    }

    /// Renders the conflict at `path` as conflict-marker text, the same
    /// way a real jj working copy would show it. Raises `JjError` if
    /// `path` isn't conflicted.
    fn materialize_conflict(
        &self,
        py: Python<'_>,
        settings: &crate::settings::PyUserSettings,
        path: &str,
    ) -> PyResult<Vec<u8>> {
        py.detach(|| {
            crate::conflicts::materialize_conflict(self, settings, path)
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
        py: Python<'_>,
        repo: &PyReadonlyRepo,
        path: &str,
    ) -> PyResult<Vec<crate::annotate::PyAnnotationLine>> {
        py.detach(|| {
            crate::annotate::annotate(self, repo, path)
        })
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
