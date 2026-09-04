use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::graph::{GraphEdgeType, TopoGroupedGraph};
use jj_lib::repo::Repo as _;
use renderdag::{Ancestor, GraphRowRenderer, Renderer};

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
    pub(crate) target: PyCommitId,
    pub(crate) edge_type: String,
}

/// One row of `ReadonlyRepo.log_graph()`: a commit plus its edges to
/// whichever ancestors are relevant within the revset (see `GraphEdge`).
#[pyclass(name = "GraphNode", frozen, get_all)]
pub struct PyGraphNode {
    commit: PyCommit,
    edges: Vec<PyGraphEdge>,
}

pub(crate) fn edge_type_str(edge_type: GraphEdgeType) -> &'static str {
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
/// The same graph, over a set of commits named outright rather than by
/// a revset expression.
///
/// `jj op diff` draws the commits an operation changed, and some of
/// them are hidden -- a rewrite leaves its earlier version behind. No
/// revset expression reaches those, but naming their ids does, which is
/// exactly what jj itself does here (`RevsetExpression::commits`).
pub fn commits_graph(repo: &PyReadonlyRepo, commit_ids: Vec<PyCommitId>) -> PyResult<Vec<PyGraphNode>> {
    let repo_ref = repo.inner.as_ref();
    let ids = commit_ids.into_iter().map(|id| id.0).collect();
    let expr: std::sync::Arc<jj_lib::revset::ResolvedRevsetExpression> =
        jj_lib::revset::RevsetExpression::commits(ids);
    let evaluated = expr.evaluate(repo_ref).map_err(map_revset_eval_err)?;
    let grouped = TopoGroupedGraph::new(evaluated.stream_graph(), |id| id);
    let store = repo.inner.store();

    pollster::block_on(async {
        let mut stream = Box::pin(grouped.stream());
        let mut result = Vec::new();
        while let Some((commit_id, edges)) = stream.try_next().await.map_err(map_revset_eval_err)? {
            let commit = store
                .get_commit_async(&commit_id)
                .await
                .map_err(map_backend_err)?;
            // jj drops the "missing" edges here, to keep the graph
            // concise: an ancestor outside the set is not drawn.
            let py_edges = edges
                .into_iter()
                .filter(|edge| edge.edge_type != GraphEdgeType::Missing)
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

/// jj's own graph drawing, as a stateful renderer.
///
/// jj does not draw its graph itself: it hands each row to Sapling's
/// `renderdag` crate, which owns the column bookkeeping and the box
/// glyphs. Reimplementing that would be a second drawing that agrees
/// with jj's only until one of them changes, so this binds the same
/// crate at the same version jj pins.
///
/// The renderer is stateful and rows must arrive in order, exactly as
/// in jj's `SaplingGraphLog::add_node`. `next_row` returns the whole
/// rendered row -- graph column and message laid out together, ending
/// in a newline -- because renderdag decides how many lines a row takes
/// and where the message sits among them.
#[pyclass(name = "GraphRenderer", unsendable)]
pub struct PyGraphRenderer {
    inner: Box<dyn Renderer<String, Output = String>>,
}

/// The edges of one row, as `(target, edge_type)` pairs. See
/// `GraphEdge` for the three types.
fn to_ancestors(parents: Vec<(String, String)>) -> Vec<Ancestor<String>> {
    parents
        .into_iter()
        .map(|(target, edge_type)| match edge_type.as_str() {
            "indirect" => Ancestor::Ancestor(target),
            "missing" => Ancestor::Anonymous,
            _ => Ancestor::Parent(target),
        })
        .collect()
}

#[pymethods]
impl PyGraphRenderer {
    /// `style` is jj's `ui.graph.style`: `"curved"` (the default),
    /// `"square"`, `"ascii"` or `"ascii-large"`.
    #[new]
    #[pyo3(signature = (style="curved"))]
    fn new(style: &str) -> PyResult<Self> {
        let builder = GraphRowRenderer::new().output().with_min_row_height(0);
        let inner: Box<dyn Renderer<String, Output = String>> = match style {
            "ascii" => Box::new(builder.build_ascii()),
            "ascii-large" => Box::new(builder.build_ascii_large()),
            "curved" => Box::new(builder.build_box_drawing()),
            "square" => Box::new(builder.build_box_drawing().with_square_glyphs()),
            other => {
                return Err(crate::errors::JjError::new_err(format!(
                    "unknown graph style `{other}`"
                )));
            }
        };
        Ok(Self { inner })
    }

    /// How wide the graph column is for a row, which is what jj
    /// subtracts from the terminal width before wrapping the message.
    fn width(&self, node: String, parents: Vec<(String, String)>) -> u64 {
        let ancestors = to_ancestors(parents);
        self.inner.width(Some(&node), Some(&ancestors))
    }

    /// One row: the node, its edges, the glyph to draw it with, and the
    /// text to lay beside it.
    fn next_row(
        &mut self,
        node: String,
        parents: Vec<(String, String)>,
        glyph: String,
        text: String,
    ) -> String {
        self.inner
            .next_row(node, to_ancestors(parents), glyph, text)
    }
}
