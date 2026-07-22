use pyo3::prelude::*;

use jj_lib::annotate::FileAnnotator;
use jj_lib::repo_path::RepoPathBuf;
use jj_lib::revset::RevsetExpression;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{JjError, map_backend_err, map_revset_eval_err};
use crate::ids::PyCommitId;

/// One line of a `Commit.annotate()` result: which commit last touched this
/// line, and the line's text (including its trailing newline, if any).
#[pyclass(name = "AnnotationLine", frozen, get_all)]
pub struct PyAnnotationLine {
    commit_id: PyCommitId,
    /// `True` if the search for this line's origin ran off the edge of the
    /// domain searched (here, the whole repo) before finding a definite
    /// answer -- `commit_id` is then the last commit checked, not a
    /// confirmed originator. In practice this only happens at history
    /// boundaries (e.g. a shallow/truncated clone), same as `jj file
    /// annotate`'s own boundary marker.
    is_boundary: bool,
    line: Vec<u8>,
}

/// `jj file annotate <path>` equivalent (a.k.a. blame): for each line
/// currently in `commit`'s version of the file at `path`, find which
/// ancestor commit last changed it. Searches the whole repo as the domain
/// (matching the CLI's own current default -- see `cli/src/commands/file/
/// annotate.rs`'s TODO about narrowing it).
pub fn annotate(
    commit: &PyCommit,
    repo: &PyReadonlyRepo,
    path: &str,
) -> PyResult<Vec<PyAnnotationLine>> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let mut annotator = pollster::block_on(FileAnnotator::from_commit(&commit.inner, &repo_path))
        .map_err(map_backend_err)?;
    pollster::block_on(annotator.compute(repo.inner.as_ref(), &RevsetExpression::all()))
        .map_err(map_revset_eval_err)?;
    let annotation = annotator.to_annotation();
    Ok(annotation
        .lines()
        .map(|(result, line)| {
            let (commit_id, is_boundary) = match result {
                Ok(id) => (id.clone(), false),
                Err(id) => (id.clone(), true),
            };
            PyAnnotationLine {
                commit_id: PyCommitId(commit_id),
                is_boundary,
                line: line.to_vec(),
            }
        })
        .collect())
}
