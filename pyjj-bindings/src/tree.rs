use futures::StreamExt as _;
use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::backend::{FileId, TreeValue};
use jj_lib::copies::{CopyOperation, CopyRecords};
use jj_lib::merge::MergedTreeValue;
use jj_lib::merged_tree::TreeDiffEntry;

use crate::commit::PyCommit;
use crate::errors::map_backend_err;

/// One changed path between two commits' trees.
#[pyclass(name = "DiffEntry", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyDiffEntry {
    #[pyo3(get)]
    pub path: String,
    /// One of `"added"`, `"removed"`, `"modified"`, `"executable"`,
    /// `"copied"`, `"renamed"`.
    ///
    /// `"executable"` means only the executable bit changed (content
    /// identical) — distinguished from a content `"modified"` by comparing
    /// the resolved file ids on both sides, not just presence. Anything
    /// with an unresolved conflict on either side (or a symlink/tree/
    /// submodule value) falls back to `"modified"`. `"copied"`/`"renamed"`
    /// are only ever produced by `Commit.diff_with_copies()` — plain
    /// `Commit.diff()` never detects copies, so a rename there shows up as
    /// a `"removed"` + `"added"` pair.
    #[pyo3(get)]
    pub status: String,
    /// For `"copied"`/`"renamed"` entries (from `diff_with_copies()`), the
    /// path this entry's content came from. `None` otherwise.
    #[pyo3(get)]
    pub source_path: Option<String>,
    /// The executable bit of the file at `path` after the change (or
    /// before, for a `"removed"` entry) — `None` if this path isn't a
    /// resolvable regular file on either side (e.g. a symlink, a
    /// directory, or a conflict).
    #[pyo3(get)]
    pub executable: Option<bool>,
}

/// Resolves `value` to a plain `TreeValue::File`'s `(id, executable)`, or
/// `None` for anything else (conflicted, symlink, tree, submodule, absent).
fn resolved_file(value: &MergedTreeValue) -> Option<(FileId, bool)> {
    match value.as_resolved()?.as_ref()? {
        TreeValue::File { id, executable, .. } => Some((id.clone(), *executable)),
        _ => None,
    }
}

#[pymethods]
impl PyDiffEntry {
    fn __repr__(&self) -> String {
        match &self.source_path {
            Some(source) => format!("DiffEntry({}, {} -> {})", self.status, source, self.path),
            None => format!("DiffEntry({}, {})", self.status, self.path),
        }
    }
}

/// Path-level diff between `from`'s and `to`'s trees (no file content, no
/// copy/rename detection — every changed path is added/removed/modified; a
/// rename shows up as a "removed" + "added" pair at the two paths). Use
/// `diff_commits_with_copies` for copy/rename-aware diffing.
///
/// `paths`, if given, restricts the diff to those repo-relative paths (and
/// anything under them, if a path names a directory) — like `jj diff
/// <path>...`. `None` (the default) diffs the whole tree, matching
/// `EverythingMatcher`.
pub fn diff_commits(
    from: &PyCommit,
    to: &PyCommit,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyDiffEntry>> {
    let from_tree = from.inner.tree();
    let to_tree = to.inner.tree();
    let matcher = crate::rewrite::paths_matcher(paths)?;
    let stream = from_tree.diff_stream(&to_tree, matcher.as_ref());
    let entries: Vec<TreeDiffEntry> = pollster::block_on(stream.collect());

    entries
        .into_iter()
        .map(|entry| {
            let values = entry.values.map_err(map_backend_err)?;
            let before_file = resolved_file(&values.before);
            let after_file = resolved_file(&values.after);
            let status = match (values.before.is_present(), values.after.is_present()) {
                (false, true) => "added",
                (true, false) => "removed",
                _ => match (&before_file, &after_file) {
                    (Some((bid, bexec)), Some((aid, aexec))) if bid == aid && bexec != aexec => {
                        "executable"
                    }
                    _ => "modified",
                },
            };
            let executable = after_file.or(before_file).map(|(_, executable)| executable);
            Ok(PyDiffEntry {
                path: entry.path.as_internal_file_string().to_string(),
                status: status.to_string(),
                source_path: None,
                executable,
            })
        })
        .collect()
}

/// Like `diff_commits`, but detects copies and renames using the backend's
/// `get_copy_records` (content-similarity-based for the git backend, via
/// `gix`'s tree-diff rewrite tracking — the same mechanism `jj diff --git`
/// and `jj log --summary` use). A rename shows up as a single `"renamed"`
/// entry (`path` = new location, `source_path` = old location) rather than
/// a "removed" + "added" pair; a copy (source still present) shows up as
/// `"copied"`.
///
/// `paths` restricts the diff the same way as `diff_commits`.
pub fn diff_commits_with_copies(
    from: &PyCommit,
    to: &PyCommit,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyDiffEntry>> {
    let store = from.inner.store();
    let record_stream = store
        .get_copy_records(None, from.inner.id(), to.inner.id())
        .map_err(map_backend_err)?;
    let records: Vec<_> =
        pollster::block_on(record_stream.try_collect()).map_err(map_backend_err)?;
    let mut copy_records = CopyRecords::default();
    copy_records.add_records(records);

    let from_tree = from.inner.tree();
    let to_tree = to.inner.tree();
    let matcher = crate::rewrite::paths_matcher(paths)?;
    let stream = from_tree.diff_stream_with_copies(&to_tree, matcher.as_ref(), &copy_records);
    let entries: Vec<_> = pollster::block_on(stream.collect());

    entries
        .into_iter()
        .map(|entry| {
            let values = entry.values.map_err(map_backend_err)?;
            let source_path = entry.path.source.as_ref().map(|(path, _)| path.clone());
            let before_file = resolved_file(&values.before);
            let after_file = resolved_file(&values.after);
            let status = match entry.path.copy_operation() {
                Some(CopyOperation::Copy) => "copied",
                Some(CopyOperation::Rename) => "renamed",
                None => match (values.before.is_present(), values.after.is_present()) {
                    (false, true) => "added",
                    (true, false) => "removed",
                    _ => match (&before_file, &after_file) {
                        (Some((bid, bexec)), Some((aid, aexec)))
                            if bid == aid && bexec != aexec =>
                        {
                            "executable"
                        }
                        _ => "modified",
                    },
                },
            };
            let executable = after_file.or(before_file).map(|(_, executable)| executable);
            Ok(PyDiffEntry {
                path: entry.path.target.as_internal_file_string().to_string(),
                status: status.to_string(),
                source_path: source_path.map(|p| p.as_internal_file_string().to_string()),
                executable,
            })
        })
        .collect()
}
