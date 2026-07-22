use pyo3::prelude::*;

use jj_lib::absorb::{AbsorbSource, absorb_hunks, split_hunks_to_trees};
use jj_lib::repo::MutableRepo;

use crate::commit::PyCommit;
use crate::errors::map_py_err;
use crate::repo::PyTransaction;
use crate::rewrite::paths_matcher;
use crate::settings::PyUserSettings;

/// Result of `Transaction.absorb()`: which commits `jj absorb` touched.
#[pyclass(name = "AbsorbStats", frozen, get_all)]
pub struct PyAbsorbStats {
    /// The rewritten source commit with the absorbed hunks removed, or
    /// `None` if it was abandoned (all its changes were absorbed and it had
    /// no description) or nothing was moved out of it at all.
    source: Option<PyCommit>,
    /// The rewritten destination commits that hunks were absorbed into, in
    /// forward topological order (does not include `source`).
    destinations: Vec<PyCommit>,
    /// Number of descendant commits rebased as a side effect (not counting
    /// `destinations` themselves).
    num_rebased: usize,
}

/// `jj absorb`: splits the changes in `source` and moves each hunk into the
/// closest ancestor (among `destinations`) where the corresponding lines
/// were last modified, based on the same file-annotation machinery
/// `Commit.annotate()` uses. `source` is abandoned if every hunk was
/// absorbed away and it has no description, matching the CLI's own rule.
///
/// `destinations` is a revset expression (default `"mutable()"`, same as
/// the CLI) restricting which ancestors of `source` are eligible; `paths`
/// restricts which files are considered (default: all of them). Hunks that
/// can't be unambiguously attributed to a single destination are left
/// alone in `source`.
pub fn absorb(
    tx: &PyTransaction,
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    source_commit: &PyCommit,
    destinations: &str,
    paths: Option<Vec<String>>,
) -> PyResult<PyAbsorbStats> {
    let matcher = paths_matcher(paths)?;
    let destinations_expr = crate::revset::resolve_revset(
        mut_repo,
        tx.workspace_root(),
        tx.workspace_name(),
        settings,
        destinations,
    )?;

    let source = pollster::block_on(AbsorbSource::from_commit(
        mut_repo,
        source_commit.inner.clone(),
    ))
    .map_err(map_py_err)?;
    let selected_trees = pollster::block_on(split_hunks_to_trees(
        mut_repo,
        &source,
        &destinations_expr,
        matcher.as_ref(),
    ))
    .map_err(map_py_err)?;
    let stats = pollster::block_on(absorb_hunks(
        mut_repo,
        &source,
        selected_trees.target_commits,
    ))
    .map_err(map_py_err)?;

    Ok(PyAbsorbStats {
        source: stats
            .rewritten_source
            .map(|inner| PyCommit { inner, _repo: None }),
        destinations: stats
            .rewritten_destinations
            .into_iter()
            .map(|inner| PyCommit { inner, _repo: None })
            .collect(),
        num_rebased: stats.num_rebased,
    })
}
