use futures::StreamExt as _;
use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::backend::{FileId, TreeValue};
use jj_lib::copies::{CopyOperation, CopyRecords};
use jj_lib::merge::MergedTreeValue;
use jj_lib::merged_tree::{MergedTree, TreeDiffEntry};

use crate::commit::{PyCommit, PyReadonlyRepo};
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
    diff_trees(&from.inner.tree(), &to.inner.tree(), paths)
}

/// The shared half of `diff_commits`: two trees in, diff entries out.
fn diff_trees(
    from_tree: &MergedTree,
    to_tree: &MergedTree,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyDiffEntry>> {
    let matcher = crate::rewrite::paths_matcher(paths)?;
    let stream = from_tree.diff_stream(to_tree, matcher.as_ref());
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

/// `jj interdiff --from A --to B`: the difference between two commits'
/// *diffs*, rather than between their contents.
///
/// `jj_lib::rewrite::rebase_to_dest_parent` rebases `from`'s tree onto
/// `to`'s parents, and the answer is that tree diffed against `to`'s. The
/// distinction from a plain diff only shows when the two commits have
/// different parents: a plain diff includes everything that changed
/// between those parents, and this does not.
pub fn interdiff_commits(
    repo: &PyReadonlyRepo,
    from: &PyCommit,
    to: &PyCommit,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyDiffEntry>> {
    let from_tree = pollster::block_on(jj_lib::rewrite::rebase_to_dest_parent(
        repo.inner.as_ref(),
        std::slice::from_ref(&from.inner),
        &to.inner,
    ))
    .map_err(map_backend_err)?;
    diff_trees(&from_tree, &to.inner.tree(), paths)
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

/// Lines and bytes changed at one path, from `Commit.diff_stats()`.
///
/// `added`/`removed` are line counts, and `None` for a binary file --
/// jj counts neither, and prints the byte delta instead. A conflicted
/// file is materialized with markers first, so its markers count as
/// lines the same way they do in `jj diff --stat`.
#[pyclass(name = "DiffStat", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyDiffStat {
    pub path: String,
    /// Same vocabulary as `DiffEntry.status`, minus `"executable"`: a
    /// mode-only change moves no lines, so it reads as `"modified"`.
    pub status: String,
    pub added: Option<usize>,
    pub removed: Option<usize>,
    /// Size change in bytes, negative when the file shrank.
    pub bytes_delta: isize,
    pub binary: bool,
}

#[pymethods]
impl PyDiffStat {
    fn __repr__(&self) -> String {
        match (self.added, self.removed) {
            (Some(added), Some(removed)) => {
                format!("DiffStat({}, +{added} -{removed})", self.path)
            }
            _ => format!("DiffStat({}, binary {:+})", self.path, self.bytes_delta),
        }
    }
}

/// `jj diff --stat`'s numbers: lines added and removed per path.
///
/// This mirrors `DiffStats::calculate` in `cli/src/diff_util.rs`. Each
/// side is materialized -- so a conflict becomes its marker text -- and
/// the two are compared line by line; every differing hunk contributes
/// its left lines to `removed` and its right lines to `added`.
///
/// Binary is decided the way jj (and git) decide it: a NUL byte in the
/// first 8000 bytes. Such a file reports `None` for both counts.
pub fn diff_stats(
    from: &PyCommit,
    to: &PyCommit,
    settings: &crate::settings::PyUserSettings,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyDiffStat>> {
    use jj_lib::conflict_labels::ConflictLabels;
    use jj_lib::conflicts::{
        ConflictMarkerStyle, ConflictMaterializeOptions, materialized_diff_stream,
    };
    use jj_lib::diff::DiffHunkKind;
    use jj_lib::diff_presentation::{diff_by_line, LineCompareMode};
    use jj_lib::merge::Diff;

    let store = from.inner.store();
    let marker_style: ConflictMarkerStyle = settings
        .0
        .get("ui.conflict-marker-style")
        .map_err(crate::errors::map_py_err)?;
    let materialize_options = ConflictMaterializeOptions {
        marker_style,
        marker_len: None,
        merge: store.merge_options().clone(),
    };

    let from_tree = from.inner.tree();
    let to_tree = to.inner.tree();
    let matcher = crate::rewrite::paths_matcher(paths)?;
    // No copy detection: `jj diff --stat` only runs it when asked, and a
    // rename then reads as a removal plus an addition, which is what the
    // plain `diff()` binding reports too.
    let copy_records = CopyRecords::default();
    let tree_diff = from_tree.diff_stream_with_copies(&to_tree, matcher.as_ref(), &copy_records);
    let labels = ConflictLabels::unlabeled();

    pollster::block_on(async {
        let mut stream = Box::pin(materialized_diff_stream(
            store,
            Box::pin(tree_diff),
            Diff::new(&labels, &labels),
        ));
        let mut out = Vec::new();
        while let Some(entry) = stream.next().await {
            let values = entry.values.map_err(map_backend_err)?;
            let status = match (values.before.is_present(), values.after.is_present()) {
                (false, true) => "added",
                (true, false) => "removed",
                _ => "modified",
            };
            let before = read_side(
                entry.path.source(),
                values.before,
                &materialize_options,
            )
            .await?;
            let after = read_side(
                entry.path.target(),
                values.after,
                &materialize_options,
            )
            .await?;

            let (added, removed) = if before.is_binary || after.is_binary {
                (None, None)
            } else {
                let diff = diff_by_line([&before.contents, &after.contents], &LineCompareMode::Exact);
                let mut added = 0usize;
                let mut removed = 0usize;
                for hunk in diff.hunks() {
                    if hunk.kind == DiffHunkKind::Different {
                        let [left, right] = hunk.contents[..].try_into().unwrap();
                        removed += left.split_inclusive(|b| *b == b'\n').count();
                        added += right.split_inclusive(|b| *b == b'\n').count();
                    }
                }
                (Some(added), Some(removed))
            };

            out.push(PyDiffStat {
                path: entry.path.target().as_internal_file_string().to_string(),
                status: status.to_string(),
                added,
                removed,
                bytes_delta: after.contents.len() as isize - before.contents.len() as isize,
                binary: before.is_binary || after.is_binary,
            });
        }
        Ok(out)
    })
}

/// One side of a stat entry as bytes, with jj's binary verdict.
///
/// Anything that is not a plain file reads as empty and non-binary,
/// which is how `DiffStats` treats it: a symlink or a submodule moves
/// no lines.
async fn read_side(
    path: &jj_lib::repo_path::RepoPath,
    value: jj_lib::conflicts::MaterializedTreeValue,
    options: &jj_lib::conflicts::ConflictMaterializeOptions,
) -> PyResult<jj_lib::diff_presentation::FileContent<bstr::BString>> {
    use bstr::BString;
    use jj_lib::conflicts::{materialize_merge_result_to_bytes, MaterializedTreeValue};
    use jj_lib::diff_presentation::{file_content_for_diff, FileContent};

    Ok(match value {
        MaterializedTreeValue::File(mut file) => {
            file_content_for_diff(path, &mut file, |content| content)
                .await
                .map_err(map_backend_err)?
        }
        MaterializedTreeValue::FileConflict(conflict) => FileContent {
            is_binary: false,
            contents: BString::from(materialize_merge_result_to_bytes(
                &conflict.contents,
                &conflict.labels,
                options,
            )),
        },
        _ => FileContent {
            is_binary: false,
            contents: BString::default(),
        },
    })
}

/// One changed path with both sides materialized the way `jj diff --git`
/// needs them: the octal mode, the abbreviated blob hash and the content.
///
/// `before_mode` is `None` for an added path and `after_mode` is `None`
/// for a removed one; jj prints `new file mode` / `deleted file mode`
/// from exactly that. The hashes are jj's, truncated to ten characters
/// as jj truncates them, and are `"0000000000"` where there is no file.
#[pyclass(name = "GitDiffFile", frozen)]
pub struct PyGitDiffFile {
    /// The path after the change.
    #[pyo3(get)]
    pub path: String,
    /// The path before the change. Differs from `path` only for a copy
    /// or a rename.
    #[pyo3(get)]
    pub source_path: String,
    /// `"copy"`, `"rename"`, or `None` when the path did not move.
    #[pyo3(get)]
    pub copy_operation: Option<String>,
    #[pyo3(get)]
    pub before_mode: Option<String>,
    #[pyo3(get)]
    pub after_mode: Option<String>,
    #[pyo3(get)]
    pub before_hash: String,
    #[pyo3(get)]
    pub after_hash: String,
    #[pyo3(get)]
    pub before_content: Vec<u8>,
    #[pyo3(get)]
    pub after_content: Vec<u8>,
    /// True when either side looks binary, by jj's rule: a NUL byte in
    /// the first 8000 bytes. jj prints "Binary files ... differ" instead
    /// of hunks for these.
    #[pyo3(get)]
    pub is_binary: bool,
}

#[pymethods]
impl PyGitDiffFile {
    fn __repr__(&self) -> String {
        format!("GitDiffFile({})", self.path)
    }
}

/// The per-file halves of `jj diff --git`, straight from `jj_lib`'s
/// `git_diff_part`.
///
/// Formatting is left to the caller; what this settles is the part that
/// has to agree with jj -- which mode string, which hash, and what the
/// content is once conflicts are materialized. Pair it with
/// `unified_hunks()` for the hunks.
///
/// `copies` turns on the backend's copy and rename detection, as `jj
/// diff --git` does by default.
pub fn git_diff_files(
    from: &PyCommit,
    to: &PyCommit,
    settings: &crate::settings::PyUserSettings,
    paths: Option<Vec<String>>,
    copies: bool,
) -> PyResult<Vec<PyGitDiffFile>> {
    git_diff_trees(
        &from.inner.tree(),
        &to.inner.tree(),
        from.inner.store(),
        settings,
        paths,
        copies.then(|| (from.inner.id().clone(), to.inner.id().clone())),
    )
}

/// The interdiff of two commits, in the same per-file shape as
/// `git_diff_files`.
///
/// `interdiff_commits` answers which paths differ; this answers what
/// their content is, so every format `jj interdiff` can print has the
/// same source as the corresponding `jj diff` format.
pub fn interdiff_files(
    repo: &PyReadonlyRepo,
    from: &PyCommit,
    to: &PyCommit,
    settings: &crate::settings::PyUserSettings,
    paths: Option<Vec<String>>,
) -> PyResult<Vec<PyGitDiffFile>> {
    let from_tree = pollster::block_on(jj_lib::rewrite::rebase_to_dest_parent(
        repo.inner.as_ref(),
        std::slice::from_ref(&from.inner),
        &to.inner,
    ))
    .map_err(map_backend_err)?;
    // No copy detection: the rebased tree has no commit id to ask the
    // backend about, and `jj interdiff` does not detect copies either.
    git_diff_trees(
        &from_tree,
        &to.inner.tree(),
        to.inner.store(),
        settings,
        paths,
        None,
    )
}

/// The shared half: two trees in, per-file git-diff parts out.
fn git_diff_trees(
    from_tree: &MergedTree,
    to_tree: &MergedTree,
    store: &std::sync::Arc<jj_lib::store::Store>,
    settings: &crate::settings::PyUserSettings,
    paths: Option<Vec<String>>,
    copy_ids: Option<(jj_lib::backend::CommitId, jj_lib::backend::CommitId)>,
) -> PyResult<Vec<PyGitDiffFile>> {
    use jj_lib::conflict_labels::ConflictLabels;
    use jj_lib::conflicts::{
        ConflictMarkerStyle, ConflictMaterializeOptions, materialized_diff_stream,
    };
    use jj_lib::diff_presentation::unified::git_diff_part;
    use jj_lib::merge::Diff;

    let marker_style: ConflictMarkerStyle = settings
        .0
        .get("ui.conflict-marker-style")
        .map_err(crate::errors::map_py_err)?;
    let materialize_options = ConflictMaterializeOptions {
        marker_style,
        marker_len: None,
        merge: store.merge_options().clone(),
    };

    let matcher = crate::rewrite::paths_matcher(paths)?;
    let mut copy_records = CopyRecords::default();
    if let Some((from_id, to_id)) = copy_ids {
        let record_stream = store
            .get_copy_records(None, &from_id, &to_id)
            .map_err(map_backend_err)?;
        let records: Vec<_> =
            pollster::block_on(record_stream.try_collect()).map_err(map_backend_err)?;
        copy_records.add_records(records);
    }
    let tree_diff = from_tree.diff_stream_with_copies(to_tree, matcher.as_ref(), &copy_records);
    let labels = ConflictLabels::unlabeled();

    pollster::block_on(async {
        let mut stream = Box::pin(materialized_diff_stream(
            store,
            Box::pin(tree_diff),
            Diff::new(&labels, &labels),
        ));
        let mut out = Vec::new();
        while let Some(entry) = stream.next().await {
            let values = entry.values.map_err(map_backend_err)?;
            let before = git_diff_part(entry.path.source(), values.before, &materialize_options)
                .await
                .map_err(crate::errors::map_py_err)?;
            let after = git_diff_part(entry.path.target(), values.after, &materialize_options)
                .await
                .map_err(crate::errors::map_py_err)?;
            let copy_operation = entry.path.copy_operation().map(|op| {
                match op {
                    CopyOperation::Copy => "copy",
                    CopyOperation::Rename => "rename",
                }
                .to_owned()
            });
            out.push(PyGitDiffFile {
                path: entry.path.target().as_internal_file_string().to_string(),
                source_path: entry.path.source().as_internal_file_string().to_string(),
                copy_operation,
                before_mode: before.mode.map(|m| m.to_owned()),
                after_mode: after.mode.map(|m| m.to_owned()),
                before_hash: before.hash,
                after_hash: after.hash,
                is_binary: before.content.is_binary || after.content.is_binary,
                before_content: before.content.contents.into(),
                after_content: after.content.contents.into(),
            });
        }
        Ok(out)
    })
}
