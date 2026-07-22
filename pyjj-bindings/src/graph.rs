use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::graph::{GraphEdgeType, TopoGroupedGraph};
use jj_lib::repo::Repo as _;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_backend_err, map_revset_eval_err};
use crate::ids::PyCommitId;
use crate::settings::PyUserSettings;

/// One edge in a `GraphNode`, pointing at an ancestor.
///
/// `edge_type` is `"direct"` (an actual parent, present in the revset's
/// result), `"indirect"` (the nearest *visible* ancestor, when one or more
/// intermediate commits were filtered out of the revset -- the same "line
/// skips past elided commits" behavior `jj log` itself draws), or
/// `"missing"` (an ancestor outside the revset's domain entirely, e.g. a
/// shallow/truncated history boundary).
#[pyclass(name = "GraphEdge", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyGraphEdge {
    target: PyCommitId,
    edge_type: String,
}

/// One row of `ReadonlyRepo.log_graph()`: a commit plus its edges to
/// whichever ancestors are relevant within the revset (see `GraphEdge`).
#[pyclass(name = "GraphNode", frozen, get_all)]
pub struct PyGraphNode {
    commit: PyCommit,
    edges: Vec<PyGraphEdge>,
}

fn edge_type_str(edge_type: GraphEdgeType) -> &'static str {
    match edge_type {
        GraphEdgeType::Direct => "direct",
        GraphEdgeType::Indirect => "indirect",
        GraphEdgeType::Missing => "missing",
    }
}

/// `jj log`'s graph, structured: like `revset()`, but each commit comes
/// with edges to its relevant ancestors (see `GraphEdge`) instead of being
/// a flat list, and rows are topologically grouped (`jj_lib::graph::
/// TopoGroupedGraph`, the same primitive `cli/src/commands/log.rs` itself
/// uses) so a branch's commits stay contiguous rather than interleaving
/// with unrelated branches -- the same ordering `jj log` shows by default.
/// `limit`, if given, stops after that many rows (applied to the grouped
/// stream, same as `jj log -n`).
pub fn log_graph(
    repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    revision: &str,
    limit: Option<usize>,
) -> PyResult<Vec<PyGraphNode>> {
    let repo_ref = repo.inner.as_ref();
    let resolved = crate::revset::resolve_revset(
        repo_ref,
        &repo.workspace_root,
        &repo.workspace_name,
        settings,
        revision,
    )?;
    let evaluated = resolved.evaluate(repo_ref).map_err(map_revset_eval_err)?;
    let grouped = TopoGroupedGraph::new(evaluated.stream_graph(), |id| id);
    let store = repo.inner.store();

    pollster::block_on(async {
        let mut stream = Box::pin(grouped.stream());
        let mut result = Vec::new();
        while let Some((commit_id, edges)) = stream.try_next().await.map_err(map_revset_eval_err)? {
            if limit.is_some_and(|limit| result.len() >= limit) {
                break;
            }
            let commit = store
                .get_commit_async(&commit_id)
                .await
                .map_err(map_backend_err)?;
            let py_edges = edges
                .into_iter()
                .map(|edge| PyGraphEdge {
                    target: PyCommitId::from(edge.target),
                    edge_type: edge_type_str(edge.edge_type).to_string(),
                })
                .collect();
            result.push(PyGraphNode {
                commit: PyCommit {
                    inner: commit,
                    _repo: Some(repo.inner.clone()),
                },
                edges: py_edges,
            });
        }
        Ok(result)
    })
}
