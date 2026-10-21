use pyo3::prelude::*;

use jj_lib::converge::{
    ConvergedAttribute, TruncatedEvolutionGraph, apply_solution, converge_change,
    find_divergent_changes,
};
use jj_lib::repo::MutableRepo;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_py_err, map_revset_eval_err};
use crate::ids::{PyChangeId, PyCommitId, PySignature};
use crate::repo::PyTransaction;
use crate::settings::PyUserSettings;

/// One divergent change: a change id naming two or more visible commits.
#[pyclass(name = "DivergentChange", module = "pyjj_bindings", frozen, skip_from_py_object)]
#[derive(Clone)]
pub struct PyDivergentChange {
    change_id: PyChangeId,
    commits: Vec<PyCommit>,
}

#[pymethods]
impl PyDivergentChange {
    #[getter]
    fn change_id(&self) -> PyChangeId {
        self.change_id.clone()
    }

    #[getter]
    fn commits(&self) -> Vec<PyCommit> {
        self.commits.clone()
    }
}

/// One pyclass per converged attribute (author, description, parents),
/// all with the same shape: the solved-or-not state of that attribute.
/// When `solved` is false, `base_commit` names a commit to merge from and
/// `excluded` names divergent commits to leave out of that merge -- the
/// hints `jj converge`'s interactive prompts consume. A headless caller
/// treats unsolved as failure.
macro_rules! converged_attribute {
    ($name:ident, $py_name:literal, $jj:ty, $value:ty, $convert:expr) => {
        #[pyclass(name = $py_name, module = "pyjj_bindings", frozen, get_all, skip_from_py_object)]
        #[derive(Clone)]
        pub struct $name {
            solved: bool,
            value: Option<$value>,
            base_commit: Option<PyCommitId>,
            excluded: Vec<PyCommitId>,
        }

        impl From<ConvergedAttribute<$jj>> for $name {
            fn from(attr: ConvergedAttribute<$jj>) -> Self {
                match attr {
                    ConvergedAttribute::Solved(value) => Self {
                        solved: true,
                        value: Some($convert(value)),
                        base_commit: None,
                        excluded: vec![],
                    },
                    ConvergedAttribute::Unsolved {
                        base_commit,
                        excluded_divergent_commits,
                    } => Self {
                        solved: false,
                        value: None,
                        base_commit: Some(PyCommitId::from(base_commit)),
                        excluded: excluded_divergent_commits
                            .into_iter()
                            .map(PyCommitId::from)
                            .collect(),
                    },
                }
            }
        }
    };
}

converged_attribute!(
    PyConvergedAuthor,
    "ConvergedAuthor",
    jj_lib::backend::Signature,
    PySignature,
    PySignature::from
);
converged_attribute!(
    PyConvergedDescription,
    "ConvergedDescription",
    String,
    String,
    std::convert::identity
);
converged_attribute!(
    PyConvergedParents,
    "ConvergedParents",
    Vec<jj_lib::backend::CommitId>,
    Vec<PyCommitId>,
    |ids: Vec<jj_lib::backend::CommitId>| ids.into_iter().map(PyCommitId::from).collect()
);

/// The proposed solution tree. Opaque: Python never builds one, it only
/// carries the handle from one `converge()` call into the next (or into
/// `apply_converge_solution()`), mirroring how the CLI threads
/// `TreeIdsAndLabels` through its two `converge_change` calls.
#[pyclass(name = "ConvergeTree", module = "pyjj_bindings", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyConvergeTree {
    pub(crate) inner: jj_lib::converge::TreeIdsAndLabels,
}

/// The proposed solution for converging one change: a solved-or-not
/// verdict per attribute, plus the tree (absent until the parents are
/// settled -- see `jj_lib::converge::converge_change`).
#[pyclass(name = "ConvergeResult", module = "pyjj_bindings", frozen, skip_from_py_object)]
#[derive(Clone)]
pub struct PyConvergeResult {
    author: PyConvergedAuthor,
    description: PyConvergedDescription,
    parents: PyConvergedParents,
    tree: Option<PyConvergeTree>,
}

#[pymethods]
impl PyConvergeResult {
    #[getter]
    fn author(&self) -> PyConvergedAuthor {
        self.author.clone()
    }

    #[getter]
    fn description(&self) -> PyConvergedDescription {
        self.description.clone()
    }

    #[getter]
    fn parents(&self) -> PyConvergedParents {
        self.parents.clone()
    }

    #[getter]
    fn tree(&self) -> Option<PyConvergeTree> {
        self.tree.clone()
    }
}

/// The truncated evolution graph for one divergent change: the
/// same-change-id predecessors back to their closest common dominator.
/// Built from the commits to converge; `converge()` runs the heuristics.
#[pyclass(name = "TruncatedEvolutionGraph", frozen)]
pub struct PyTruncatedEvolutionGraph {
    inner: TruncatedEvolutionGraph,
}

#[pymethods]
impl PyTruncatedEvolutionGraph {
    #[new]
    fn new(repo: &PyReadonlyRepo, commits: Vec<PyCommit>) -> PyResult<Self> {
        let inner = commits.into_iter().map(|c| c.inner.clone()).collect();
        let graph = pollster::block_on(TruncatedEvolutionGraph::new(repo.inner.clone(), inner))
            .map_err(map_py_err)?;
        Ok(Self { inner: graph })
    }

    /// The change id of the divergent commits the graph was built from.
    #[getter]
    fn change_id(&self) -> PyChangeId {
        PyChangeId::from(self.inner.change_id().clone())
    }

    /// The divergent commit ids, in the order they were given.
    #[getter]
    fn divergent_commit_ids(&self) -> Vec<PyCommitId> {
        self.inner
            .divergent_commit_ids()
            .iter()
            .map(PyCommitId::from)
            .collect()
    }

    /// Attempt to converge the change automatically. Any of `author`,
    /// `description`, `parents`, `tree` may be supplied outright (taken
    /// as solved, same as the CLI's second pass once it knows them);
    /// the rest are derived by heuristic. A `None` tree with unsolved
    /// parents means the tree is not computable yet -- settle the
    /// parents first, then call again.
    #[pyo3(signature = (author=None, description=None, parents=None, tree=None))]
    fn converge(
        &self,
        author: Option<PySignature>,
        description: Option<String>,
        parents: Option<Vec<PyCommitId>>,
        tree: Option<PyConvergeTree>,
    ) -> PyResult<PyConvergeResult> {
        let result = pollster::block_on(converge_change(
            &self.inner,
            author.map(|a| a.0),
            description,
            parents.map(|ids| ids.into_iter().map(|id| id.0).collect()),
            tree.map(|t| t.inner.clone()),
        ))
        .map_err(map_py_err)?;
        Ok(PyConvergeResult {
            author: result.author.into(),
            description: result.description.into(),
            parents: result.parents.into(),
            tree: result.tree.map(|inner| PyConvergeTree { inner }),
        })
    }
}

/// `jj converge`'s search half: evaluate `revset` and group the commits
/// sharing a change id, keeping only the actually-divergent groups (two
/// or more commits), in change-id order.
pub fn divergent_changes_for(
    repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    revset: &str,
) -> PyResult<Vec<PyDivergentChange>> {
    let repo_ref = repo.inner.as_ref();
    let resolved = crate::revset::resolve_revset(
        repo_ref,
        &repo.workspace_root,
        &repo.workspace_name,
        settings,
        revset,
    )?;
    let by_change = pollster::block_on(find_divergent_changes(&repo.inner, resolved))
        .map_err(map_revset_eval_err)?;
    Ok(by_change
        .into_iter()
        .map(|(change_id, commits)| PyDivergentChange {
            change_id: PyChangeId::from(change_id),
            commits: commits
                .into_iter()
                .map(|inner| PyCommit {
                    inner,
                    _repo: Some(repo.inner.clone()),
                })
                .collect(),
        })
        .collect())
}

/// `jj converge`'s write half: record `author`/`description`/`parents`/
/// `tree` as a new commit with `change_id` that supersedes
/// `divergent_ids`, rebasing descendants onto it. Returns the solution
/// commit and the number of rebased descendants. `rebase_descendants()`
/// is still required before `commit()`, same as every other rewrite
/// here -- `apply_solution` rebases internally but leaves the
/// pending-rewrite record `Transaction::commit()` asserts on.
#[allow(clippy::too_many_arguments)]
pub fn apply_converge_solution(
    _tx: &PyTransaction,
    mut_repo: &mut MutableRepo,
    author: PySignature,
    description: String,
    parents: Vec<PyCommitId>,
    tree: &PyConvergeTree,
    change_id: &PyChangeId,
    divergent_ids: Vec<PyCommitId>,
) -> PyResult<(PyCommit, usize)> {
    let divergent: Vec<jj_lib::backend::CommitId> =
        divergent_ids.into_iter().map(|id| id.0).collect();
    let (solution, num_rebased) = pollster::block_on(apply_solution(
        author.0,
        description,
        parents.into_iter().map(|id| id.0).collect(),
        tree.inner.clone(),
        change_id.0.clone(),
        &divergent,
        mut_repo,
    ))
    .map_err(map_py_err)?;
    Ok((
        PyCommit {
            inner: solution,
            _repo: None,
        },
        num_rebased,
    ))
}
