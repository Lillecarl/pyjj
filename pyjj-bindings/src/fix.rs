use std::collections::{HashMap, HashSet};

use futures::AsyncReadExt as _;
use pyo3::prelude::*;

use jj_lib::backend::FileId;
use jj_lib::fix::{FileFixer, FileToFix, FixError, fix_files as lib_fix_files};
use jj_lib::object_id::ObjectId as _;
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::store::Store;

use crate::errors::map_py_err;
use crate::ids::PyCommitId;
use crate::repo::PyTransaction;
use crate::rewrite::paths_matcher;
use crate::settings::PyUserSettings;

/// A file `jj fix` (or its Python equivalent) may want to transform: the
/// current content at `path` in some (possibly several, deduplicated)
/// commit(s). `key` is an opaque identifier -- pass it back unchanged in the
/// `fixes` mapping given to `Transaction.fix_apply()` to say what this
/// file's new content should be.
#[pyclass(name = "FileToFix", frozen, get_all)]
pub struct PyFileToFix {
    key: String,
    path: String,
    content: Vec<u8>,
}

/// Result of `Transaction.fix_apply()`.
#[pyclass(name = "FixSummary", frozen, get_all)]
pub struct PyFixSummary {
    /// Commits that had at least one matching file (whether or not their
    /// content actually changed).
    num_checked_commits: i32,
    /// Commits that were rewritten because some file's content changed.
    num_fixed_commits: i32,
    /// Old commit id -> new commit id, for every rewritten commit.
    rewrites: HashMap<PyCommitId, PyCommitId>,
}

/// A `FileFixer` that changes nothing -- it just records every unique
/// `FileToFix` it's asked about, so `fix_enumerate()` can hand that
/// (deduplicated, descendant-propagated) set back to Python as plain data
/// instead of routing "how do I fix a file" through a Python callback.
struct RecordingFixer {
    files: Vec<FileToFix>,
}

impl FileFixer for RecordingFixer {
    fn fix_files<'a>(
        &mut self,
        _store: &Store,
        files_to_fix: &'a HashSet<FileToFix>,
    ) -> Result<HashMap<&'a FileToFix, FileId>, FixError> {
        self.files = files_to_fix.iter().cloned().collect();
        Ok(HashMap::new())
    }
}

/// A `FileFixer` that looks up each file's new content in a plain
/// Python-supplied `key -> bytes` mapping (built from an earlier
/// `fix_enumerate()` call) instead of calling back into Python per file.
/// A file whose key is absent from the mapping is left unchanged.
struct LookupFixer<'a> {
    fixes: &'a HashMap<String, Vec<u8>>,
}

impl FileFixer for LookupFixer<'_> {
    fn fix_files<'a>(
        &mut self,
        store: &Store,
        files_to_fix: &'a HashSet<FileToFix>,
    ) -> Result<HashMap<&'a FileToFix, FileId>, FixError> {
        let mut result = HashMap::new();
        for file_to_fix in files_to_fix {
            if let Some(new_content) = self.fixes.get(&file_to_fix.file_id.hex()) {
                let new_file_id = pollster::block_on(
                    store.write_file(&file_to_fix.repo_path, &mut new_content.as_slice()),
                )?;
                result.insert(file_to_fix, new_file_id);
            }
        }
        Ok(result)
    }
}

/// `jj fix`'s first half: resolves `revset` (default `"reachable(@,
/// mutable())"`, same as jj's own `revsets.fix` config) and its descendants,
/// diffs each against its base, and returns the deduplicated set of
/// `(commit, path)` pairs whose current content might need fixing --
/// restricted to `paths` if given. No content is read or written by this
/// call except for round-tripping it back to Python; the transaction is
/// left otherwise untouched (nothing needs `rebase_descendants()` after
/// this alone).
///
/// Run each file's `content` through whatever external formatter/linter
/// Python wants (`subprocess`, same idiom as driving a merge tool off
/// `Commit.materialize_conflict()`), then pass a `{key: new_content}`
/// mapping for the ones that changed to `fix_apply()`.
pub fn fix_enumerate(
    tx: &PyTransaction,
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    revset: Option<&str>,
    paths: Option<Vec<String>>,
    include_unchanged_files: bool,
) -> PyResult<Vec<PyFileToFix>> {
    let root_commits = resolve_root_commits(tx, mut_repo, settings, revset)?;
    let matcher = paths_matcher(paths)?;
    let mut fixer = RecordingFixer { files: Vec::new() };
    pollster::block_on(lib_fix_files(
        root_commits,
        matcher.as_ref(),
        include_unchanged_files,
        mut_repo,
        &mut fixer,
    ))
    .map_err(map_py_err)?;

    fixer
        .files
        .into_iter()
        .map(|file_to_fix| {
            let mut buf = Vec::new();
            let mut reader = pollster::block_on(
                mut_repo
                    .store()
                    .read_file(&file_to_fix.repo_path, &file_to_fix.file_id),
            )
            .map_err(map_py_err)?;
            pollster::block_on(reader.read_to_end(&mut buf)).map_err(map_py_err)?;
            Ok(PyFileToFix {
                key: file_to_fix.file_id.hex(),
                path: file_to_fix.repo_path.as_internal_file_string().to_string(),
                content: buf,
            })
        })
        .collect()
}

/// `jj fix`'s second half: same `revset`/`paths` selection as
/// `fix_enumerate()`, but applies the given `{key: new_content}` mapping
/// (keyed by `FileToFix.key`) instead of recomputing anything, rewriting
/// each affected commit and propagating the fix to its descendants so the
/// change isn't lost (same rule real `jj fix` follows). Files whose key is
/// missing from `fixes` are left as they are. Still needs
/// `rebase_descendants()` before `commit()`, same as every other rewrite
/// here.
pub fn fix_apply(
    tx: &PyTransaction,
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    revset: Option<&str>,
    paths: Option<Vec<String>>,
    fixes: HashMap<String, Vec<u8>>,
    include_unchanged_files: bool,
) -> PyResult<PyFixSummary> {
    let root_commits = resolve_root_commits(tx, mut_repo, settings, revset)?;
    let matcher = paths_matcher(paths)?;
    let mut fixer = LookupFixer { fixes: &fixes };
    let summary = pollster::block_on(lib_fix_files(
        root_commits,
        matcher.as_ref(),
        include_unchanged_files,
        mut_repo,
        &mut fixer,
    ))
    .map_err(map_py_err)?;

    Ok(PyFixSummary {
        num_checked_commits: summary.num_checked_commits,
        num_fixed_commits: summary.num_fixed_commits,
        rewrites: summary
            .rewrites
            .into_iter()
            .map(|(old, new)| (PyCommitId::from(old), PyCommitId::from(new)))
            .collect(),
    })
}

fn resolve_root_commits(
    tx: &PyTransaction,
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    revset: Option<&str>,
) -> PyResult<Vec<jj_lib::backend::CommitId>> {
    use futures::TryStreamExt as _;

    let expr = crate::revset::resolve_revset(
        mut_repo,
        tx.workspace_root(),
        tx.workspace_name(),
        settings,
        revset.unwrap_or("reachable(@, mutable())"),
    )?;
    let evaluated = expr.evaluate(mut_repo).map_err(map_py_err)?;
    pollster::block_on(evaluated.stream().try_collect()).map_err(map_py_err)
}
