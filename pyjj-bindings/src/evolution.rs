//! `jj evolog`'s history: how one change evolved across rewrites.
//!
//! `jj_lib::evolution::walk_predecessors` streams owned
//! `CommitEvolutionEntry` values, so unlike the graph and bisect wrappers
//! there is no borrow to work around -- the stream is drained inside the
//! call and the entries handed straight to Python.

use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::evolution::walk_predecessors;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::map_py_err;
use crate::ids::PyCommitId;
use crate::operation::PyOperation;

/// One step in a change's evolution, from
/// `ReadonlyRepo.evolution_log()`.
///
/// `operation` is the operation that created or rewrote `commit`, and is
/// `None` for a commit whose creating operation is no longer in the op
/// log. `predecessor_ids` are the commits this one was rewritten from --
/// empty for the first version, and more than one where versions were
/// squashed together.
#[pyclass(name = "EvolutionEntry", frozen, get_all)]
pub struct PyEvolutionEntry {
    commit: PyCommit,
    operation: Option<PyOperation>,
    predecessor_ids: Vec<PyCommitId>,
}

/// Walk the evolution of `start_commits`, newest version first.
///
/// This is what `jj evolog` shows: every earlier version of a change,
/// found by walking the operation log rather than the commit graph, so it
/// includes versions that are no longer visible anywhere else. `limit`
/// stops after that many entries, like `jj evolog -n`.
pub fn evolution_log(
    repo: &PyReadonlyRepo,
    start_commits: Vec<PyCommitId>,
    limit: Option<usize>,
) -> PyResult<Vec<PyEvolutionEntry>> {
    let start: Vec<_> = start_commits.into_iter().map(|id| id.0).collect();
    let stream = walk_predecessors(&repo.inner, &start);
    pollster::block_on(async {
        let mut stream = Box::pin(stream);
        let mut result = Vec::new();
        while let Some(entry) = stream.try_next().await.map_err(map_py_err)? {
            if limit.is_some_and(|limit| result.len() >= limit) {
                break;
            }
            let predecessor_ids = entry
                .predecessor_ids()
                .iter()
                .cloned()
                .map(PyCommitId)
                .collect();
            result.push(PyEvolutionEntry {
                commit: PyCommit {
                    inner: entry.commit,
                    _repo: Some(repo.inner.clone()),
                },
                operation: entry.operation.map(PyOperation),
                predecessor_ids,
            });
        }
        Ok(result)
    })
}
