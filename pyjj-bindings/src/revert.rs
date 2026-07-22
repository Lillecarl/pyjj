use pyo3::prelude::*;

use jj_lib::backend::CommitId;
use jj_lib::commit::{Commit, conflict_label_for_commits};
use jj_lib::merge::Merge;
use jj_lib::merged_tree::MergedTree;
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::rewrite::merge_commit_trees;

use crate::commit::PyCommit;
use crate::errors::{JjError, map_backend_err};
use crate::ids::PyCommitId;
use crate::repo::PyCommitBuilder;

/// `jj revert` equivalent for a single revision: computes the reverse of
/// `commit`'s own changes (relative to its parents) and applies that
/// reverse as a 3-way merge on top of `new_parent_ids` -- same primitives
/// (`merge_commit_trees` + `MergedTree::merge`) `cli/src/commands/revert.rs`
/// uses for its `--onto` case.
///
/// Returns a `CommitBuilder` parented on `new_parent_ids`; the caller sets
/// a description and `write()`s it. To revert several commits in sequence
/// (each reverting on top of the previous, matching `jj revert -r a -r b`'s
/// reverse-topological-order chaining), call this repeatedly, passing the
/// previous result's id as `new_parent_ids` each time.
///
/// This only builds the new commit -- it does not rebase any existing
/// descendants of `new_parent_ids` onto it (the `--insert-after`/
/// `--insert-before` CLI behavior). Do that yourself with
/// `Transaction.rewrite_commit(child).set_parents([...])` +
/// `Transaction.rebase_descendants()`, same as arbitrary-destination rebase.
pub fn revert_commit(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    new_parent_ids: Vec<PyCommitId>,
) -> PyResult<PyCommitBuilder> {
    let new_parent_ids: Vec<CommitId> = new_parent_ids.into_iter().map(|p| p.0).collect();
    if new_parent_ids.is_empty() {
        return Err(JjError::new_err(
            "revert_commit requires at least one new parent",
        ));
    }
    let new_parents: Vec<Commit> = new_parent_ids
        .iter()
        .map(|id| {
            pollster::block_on(mut_repo.store().get_commit_async(id)).map_err(map_backend_err)
        })
        .collect::<PyResult<_>>()?;
    let new_base_tree =
        pollster::block_on(merge_commit_trees(mut_repo, &new_parents)).map_err(map_backend_err)?;
    let new_base_label = conflict_label_for_commits(&new_parents);

    let old_parents = pollster::block_on(commit.inner.parents()).map_err(map_backend_err)?;
    let old_base_tree =
        pollster::block_on(commit.inner.parent_tree(mut_repo)).map_err(map_backend_err)?;
    let old_tree = commit.inner.tree();
    let old_base_label = conflict_label_for_commits(&old_parents);

    let new_tree = pollster::block_on(MergedTree::merge(Merge::from_vec(vec![
        (
            new_base_tree,
            format!("{new_base_label} (revert destination)"),
        ),
        (
            old_tree,
            format!("{} (reverted revision)", commit.inner.conflict_label()),
        ),
        (
            old_base_tree,
            format!("{old_base_label} (parents of reverted revision)"),
        ),
    ])))
    .map_err(map_backend_err)?;

    let builder = mut_repo.new_commit(new_parent_ids, new_tree);
    Ok(PyCommitBuilder::from_rust(builder))
}
