//! `jj op diff`: what changed in the repository between two operations.
//!
//! This mirrors `compute_operation_commits_diff` and the ref-comparison
//! half of `show_op_diff` in `cli/src/commands/operation/diff.rs`.
//!
//! Two read-only repos come in, one loaded at each operation
//! (`ReadonlyRepo.load_at_operation()`). Their indexes are merged inside
//! a throwaway transaction, so a commit visible in only one of them can
//! still be looked up while the diff runs. That transaction is dropped,
//! never committed, so the call writes nothing -- `jj op diff` reads.

use std::collections::{HashMap, HashSet};
use std::slice;
use std::sync::Arc;

use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::backend::{ChangeId, CommitId};
use jj_lib::evolution::accumulate_predecessors;
use jj_lib::op_store::{RefTarget, RemoteRefState};
use jj_lib::refs::{diff_named_commit_ids, diff_named_ref_targets, diff_named_remote_refs};
use jj_lib::repo::{ReadonlyRepo, Repo};
use jj_lib::revset::{ResolvedRevsetExpression, RevsetExpression, RevsetExtensions, SymbolResolver};
use jj_lib::store::Store;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_backend_err, map_py_err, map_revset_eval_err};
use crate::settings::PyUserSettings;

/// One change that the operation created, rewrote or abandoned.
///
/// `added` holds the change's new commit -- one commit, or none at all
/// when the change was abandoned. `removed` holds what it replaced: the
/// predecessors of a rewrite, or the abandoned commit itself. `jj op
/// diff` prints `added` with a `+` and `removed` with a `-`.
#[pyclass(name = "ModifiedChange", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyModifiedChange {
    added: Vec<PyCommit>,
    removed: Vec<PyCommit>,
}

/// One side (before or after) of a changed ref.
///
/// A ref usually points at a single commit, in `commits`. It points at
/// nothing when `absent` is set -- the ref did not exist on that side --
/// and at several commits when `conflict` is set, in which case
/// `commits` holds the conflict's positive terms and `removed_commits`
/// its negative ones.
#[pyclass(name = "RefTargetSummary", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyRefTargetSummary {
    absent: bool,
    conflict: bool,
    commits: Vec<PyCommit>,
    removed_commits: Vec<PyCommit>,
    /// `"tracked"` or `"untracked"` for a remote ref, `None` for a local
    /// one. The two sides of one ref can differ here, which is why it
    /// lives on the side rather than on the change.
    state: Option<String>,
}

/// A ref (working copy, bookmark or tag) that the operation moved.
///
/// `remote` is `None` for a local ref, and the remote's name for a
/// remote-tracking one.
#[pyclass(name = "RefChange", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyRefChange {
    name: String,
    remote: Option<String>,
    /// The ref after the operation. `jj op diff` prints it with a `+`.
    after: PyRefTargetSummary,
    /// The ref before it, printed with a `-`. Named `before`/`after`
    /// rather than jj's `from`/`to` because `from` is a Python keyword,
    /// so an attribute called that would be unreachable.
    before: PyRefTargetSummary,
}

/// The whole result of `ReadonlyRepo.operation_diff()`.
///
/// `changes` comes back in the same topological order `jj op diff`
/// prints it in. The two `elided_*` fields are `(lower, upper)`
/// estimates of how many revisions fell outside the `changes_in` revset
/// and so are not listed; an `upper` of `None` means unbounded.
#[pyclass(name = "OperationDiff", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PyOperationDiff {
    changes: Vec<PyModifiedChange>,
    elided_newly_visible: (usize, Option<usize>),
    elided_newly_hidden: (usize, Option<usize>),
    changed_working_copies: Vec<PyRefChange>,
    changed_local_bookmarks: Vec<PyRefChange>,
    changed_local_tags: Vec<PyRefChange>,
    changed_remote_bookmarks: Vec<PyRefChange>,
    changed_remote_tags: Vec<PyRefChange>,
}

/// Wraps a commit id as a `Commit`, keeping `repo` alive so its store
/// outlives the call.
async fn commit_of(
    store: &Arc<Store>,
    repo: &Arc<ReadonlyRepo>,
    id: &CommitId,
) -> PyResult<PyCommit> {
    let commit = store.get_commit_async(id).await.map_err(map_backend_err)?;
    Ok(PyCommit {
        inner: commit,
        _repo: Some(repo.clone()),
    })
}

async fn commits_of(
    store: &Arc<Store>,
    repo: &Arc<ReadonlyRepo>,
    ids: impl IntoIterator<Item = CommitId>,
) -> PyResult<Vec<PyCommit>> {
    let mut out = Vec::new();
    for id in ids {
        out.push(commit_of(store, repo, &id).await?);
    }
    Ok(out)
}

/// Builds one side of a ref change, in the shape `write_ref_target_summary`
/// renders.
async fn summarize_target(
    store: &Arc<Store>,
    repo: &Arc<ReadonlyRepo>,
    target: &RefTarget,
    state: Option<&RemoteRefState>,
) -> PyResult<PyRefTargetSummary> {
    let state = state.map(|state| {
        match state {
            RemoteRefState::New => "untracked",
            RemoteRefState::Tracked => "tracked",
        }
        .to_string()
    });
    if target.is_absent() {
        return Ok(PyRefTargetSummary {
            absent: true,
            conflict: false,
            commits: vec![],
            removed_commits: vec![],
            state,
        });
    }
    let conflict = target.has_conflict();
    let commits = commits_of(store, repo, target.added_ids().cloned()).await?;
    let removed_commits = if conflict {
        commits_of(store, repo, target.removed_ids().cloned()).await?
    } else {
        vec![]
    };
    Ok(PyRefTargetSummary {
        absent: false,
        conflict,
        commits,
        removed_commits,
        state,
    })
}

/// The remote whose refs `jj op diff` hides, because a change to them is
/// already covered by the matching local ref. That is the pseudo-remote
/// jj uses for a colocated Git repo's own refs.
fn ignored_remote_name(store: &Store) -> Option<&'static jj_lib::ref_name::RemoteName> {
    if jj_lib::git::get_git_backend(store).is_ok() {
        return Some(jj_lib::git::REMOTE_NAME_FOR_LOCAL_GIT_REPO);
    }
    None
}

/// Compares the repository at two operations.
///
/// `from_repo` and `to_repo` are read-only repos loaded at the two
/// operations. `changes_in` is a revset limiting which revisions get
/// listed individually; the rest are only counted, in the `elided_*`
/// fields. It defaults to the `revsets.op-diff-changes-in` setting,
/// exactly as `jj op diff` does.
pub fn operation_diff(
    from_repo: &PyReadonlyRepo,
    to_repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    changes_in: Option<&str>,
) -> PyResult<PyOperationDiff> {
    let expression_str = match changes_in {
        Some(expr) => expr.to_string(),
        None => settings
            .0
            .get::<String>("revsets.op-diff-changes-in")
            .map_err(map_py_err)?,
    };
    // Parsed once, then resolved separately against each repo: a symbol
    // can name different commits, or none at all, on the two sides.
    let user_expr = crate::revset::parse_revset(
        &to_repo.workspace_root,
        &to_repo.workspace_name,
        settings,
        &expression_str,
    )?;
    let extensions = RevsetExtensions::new();
    let resolve = |repo: &ReadonlyRepo| -> PyResult<Arc<ResolvedRevsetExpression>> {
        let resolver = SymbolResolver::new(repo, extensions.symbol_resolvers());
        user_expr
            .resolve_user_expression(repo, &resolver)
            .map_err(map_revset_eval_err)
    };
    let from_changes_expr = resolve(&from_repo.inner)?;
    let to_changes_expr = resolve(&to_repo.inner)?;

    // A transaction only so the two indexes can be merged into one repo
    // view. It is dropped at the end of this function without ever being
    // committed, so nothing is written.
    let mut tx = to_repo.inner.start_transaction();
    tx.repo_mut()
        .merge_index(&from_repo.inner)
        .map_err(map_py_err)?;
    let merged_repo: &dyn Repo = tx.repo();
    let store = merged_repo.store().clone();
    let keep_alive = to_repo.inner.clone();

    pollster::block_on(async {
        let from_heads = from_repo.inner.view().heads().iter().cloned().collect();
        let to_heads = to_repo.inner.view().heads().iter().cloned().collect();
        let from_expr = RevsetExpression::commits(from_heads);
        let to_expr = RevsetExpression::commits(to_heads);
        let newly_hidden_expr = to_expr.range(&from_expr);
        let newly_visible_expr = from_expr.range(&to_expr);

        let predecessor_commits = accumulate_predecessors(
            slice::from_ref(to_repo.inner.operation()),
            slice::from_ref(from_repo.inner.operation()),
        )
        .await
        .map_err(map_py_err)?;

        let elided_newly_visible = newly_visible_expr
            .minus(&to_changes_expr)
            .evaluate(merged_repo)
            .map_err(map_revset_eval_err)?
            .count_estimate()
            .map_err(map_revset_eval_err)?;
        let elided_newly_hidden = newly_hidden_expr
            .minus(&from_changes_expr)
            .evaluate(merged_repo)
            .map_err(map_revset_eval_err)?
            .count_estimate()
            .map_err(map_revset_eval_err)?;

        // Commits that stopped being visible. One per change is kept, so
        // a rewrite can find what it replaced even when the operation
        // recorded no predecessor.
        let mut hidden_by_change: HashMap<ChangeId, CommitId> = HashMap::new();
        let mut abandoned: HashSet<CommitId> = HashSet::new();
        let newly_hidden = newly_hidden_expr
            .intersection(&from_changes_expr)
            .evaluate(merged_repo)
            .map_err(map_revset_eval_err)?;
        let mut stream = newly_hidden.commit_change_ids();
        while let Some((commit_id, change_id)) =
            stream.try_next().await.map_err(map_revset_eval_err)?
        {
            hidden_by_change
                .entry(change_id)
                .or_insert_with(|| commit_id.clone());
            abandoned.insert(commit_id);
        }
        drop(stream);

        // Commits that became visible. Each takes its predecessors from
        // the operation, or failing that from the hidden commit sharing
        // its change id.
        let mut changes: HashMap<CommitId, Vec<CommitId>> = HashMap::new();
        let newly_visible = newly_visible_expr
            .intersection(&to_changes_expr)
            .evaluate(merged_repo)
            .map_err(map_revset_eval_err)?;
        let mut stream = newly_visible.commit_change_ids();
        while let Some((commit_id, change_id)) =
            stream.try_next().await.map_err(map_revset_eval_err)?
        {
            let predecessor_ids: Vec<CommitId> =
                if let Some(ids) = predecessor_commits.get(&commit_id) {
                    ids.clone()
                } else if let Some(id) = hidden_by_change.get(&change_id) {
                    vec![id.clone()]
                } else {
                    vec![]
                };
            for id in &predecessor_ids {
                abandoned.remove(id);
            }
            changes.insert(commit_id, predecessor_ids);
        }
        drop(stream);

        // Whatever is left over went away without a successor.
        let abandoned: HashSet<CommitId> = abandoned;

        // Order the result the way `jj op diff` prints it: evaluating a
        // revset over the keys puts them back in topological order.
        let all_ids: Vec<CommitId> = changes
            .keys()
            .cloned()
            .chain(abandoned.iter().cloned())
            .collect();
        let ordered = RevsetExpression::commits(all_ids)
            .evaluate(merged_repo)
            .map_err(map_revset_eval_err)?;
        let mut stream = ordered.stream();
        let mut modified = Vec::new();
        while let Some(commit_id) = stream.try_next().await.map_err(map_revset_eval_err)? {
            if let Some(predecessor_ids) = changes.get(&commit_id) {
                modified.push(PyModifiedChange {
                    added: vec![commit_of(&store, &keep_alive, &commit_id).await?],
                    removed: commits_of(&store, &keep_alive, predecessor_ids.iter().cloned())
                        .await?,
                });
            } else {
                modified.push(PyModifiedChange {
                    added: vec![],
                    removed: vec![commit_of(&store, &keep_alive, &commit_id).await?],
                });
            }
        }
        drop(stream);

        let mut changed_working_copies = Vec::new();
        for (name, (from_id, to_id)) in diff_named_commit_ids(
            from_repo.inner.view().wc_commit_ids(),
            to_repo.inner.view().wc_commit_ids(),
        ) {
            let to_target = RefTarget::resolved(to_id.cloned());
            let from_target = RefTarget::resolved(from_id.cloned());
            changed_working_copies.push(PyRefChange {
                name: name.as_str().to_string(),
                remote: None,
                after: summarize_target(&store, &keep_alive, &to_target, None).await?,
                before: summarize_target(&store, &keep_alive, &from_target, None).await?,
            });
        }

        let mut changed_local_bookmarks = Vec::new();
        for (name, (from_target, to_target)) in diff_named_ref_targets(
            from_repo.inner.view().local_bookmarks(),
            to_repo.inner.view().local_bookmarks(),
        ) {
            changed_local_bookmarks.push(PyRefChange {
                name: name.as_str().to_string(),
                remote: None,
                after: summarize_target(&store, &keep_alive, to_target, None).await?,
                before: summarize_target(&store, &keep_alive, from_target, None).await?,
            });
        }

        let mut changed_local_tags = Vec::new();
        for (name, (from_target, to_target)) in diff_named_ref_targets(
            from_repo.inner.view().local_tags(),
            to_repo.inner.view().local_tags(),
        ) {
            changed_local_tags.push(PyRefChange {
                name: name.as_str().to_string(),
                remote: None,
                after: summarize_target(&store, &keep_alive, to_target, None).await?,
                before: summarize_target(&store, &keep_alive, from_target, None).await?,
            });
        }

        let ignored = ignored_remote_name(&store);
        let mut changed_remote_bookmarks = Vec::new();
        for (symbol, (from_ref, to_ref)) in diff_named_remote_refs(
            from_repo.inner.view().all_remote_bookmarks(),
            to_repo.inner.view().all_remote_bookmarks(),
        ) {
            if ignored.is_some_and(|ignored| symbol.remote == ignored) {
                continue;
            }
            changed_remote_bookmarks.push(PyRefChange {
                name: symbol.name.as_str().to_string(),
                remote: Some(symbol.remote.as_str().to_string()),
                after: summarize_target(&store, &keep_alive, &to_ref.target, Some(&to_ref.state))
                    .await?,
                before: summarize_target(&store, &keep_alive, &from_ref.target, Some(&from_ref.state))
                    .await?,
            });
        }

        let mut changed_remote_tags = Vec::new();
        for (symbol, (from_ref, to_ref)) in diff_named_remote_refs(
            from_repo.inner.view().all_remote_tags(),
            to_repo.inner.view().all_remote_tags(),
        ) {
            if ignored.is_some_and(|ignored| symbol.remote == ignored) {
                continue;
            }
            changed_remote_tags.push(PyRefChange {
                name: symbol.name.as_str().to_string(),
                remote: Some(symbol.remote.as_str().to_string()),
                after: summarize_target(&store, &keep_alive, &to_ref.target, Some(&to_ref.state))
                    .await?,
                before: summarize_target(&store, &keep_alive, &from_ref.target, Some(&from_ref.state))
                    .await?,
            });
        }

        Ok(PyOperationDiff {
            changes: modified,
            elided_newly_visible,
            elided_newly_hidden,
            changed_working_copies,
            changed_local_bookmarks,
            changed_local_tags,
            changed_remote_bookmarks,
            changed_remote_tags,
        })
    })
}

/// Folds several operations into the single one their merge represents,
/// so a repo can be loaded at "all of these at once".
///
/// `jj op diff` needs this: the from side of a merge operation is its
/// several parents, and they have to become one repo view before the
/// two sides can be compared.
pub fn merge_operations(
    repo: &PyReadonlyRepo,
    operations: Vec<crate::operation::PyOperation>,
) -> PyResult<crate::operation::PyOperation> {
    let ops = operations.into_iter().map(|op| op.0).collect();
    let merged = pollster::block_on(repo.inner.loader().merge_operations(ops, None))
        .map_err(map_py_err)?;
    Ok(crate::operation::PyOperation(merged))
}
