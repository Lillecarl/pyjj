use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::object_id::ObjectId as _;
use jj_lib::op_store::{self, OperationId};
use jj_lib::op_walk;
use jj_lib::operation::Operation;
use jj_lib::repo::{MutableRepo, ReadonlyRepo, Repo as _};

use crate::errors::{JjError, map_py_err};
use crate::operation::PyOperation;

pub const UNDO_OP_DESC_PREFIX: &str = "undo: restore to operation ";
pub const REDO_OP_DESC_PREFIX: &str = "redo: restore to operation ";

/// Full backward walk of the operation log from `repo`'s current
/// operation, newest first -- the same order `jj op log` shows. Unlike
/// `Operation.parents()` (one hop at a time), this walks the whole
/// ancestor DAG in one call.
pub fn operation_log(repo: &ReadonlyRepo) -> PyResult<Vec<PyOperation>> {
    let ops: Vec<Operation> = pollster::block_on(
        op_walk::walk_ancestors(std::slice::from_ref(repo.operation())).try_collect(),
    )
    .map_err(map_py_err)?;
    Ok(ops.into_iter().map(PyOperation).collect())
}

/// Loads an arbitrary past operation by its full hex id (as seen in
/// `Operation.id` / `operation_log()`).
pub fn load_operation(repo: &ReadonlyRepo, op_id_hex: &str) -> PyResult<PyOperation> {
    let id = OperationId::try_from_hex(op_id_hex)
        .ok_or_else(|| JjError::new_err(format!("`{op_id_hex}` is not a valid operation id")))?;
    let op = pollster::block_on(repo.loader().load_operation(&id)).map_err(map_py_err)?;
    Ok(PyOperation(op))
}

/// Result of `Workspace.op_abandon()`.
#[pyclass(name = "OpAbandonStats", frozen, get_all)]
pub struct PyOpAbandonStats {
    /// Number of operations that became unreachable (pruned).
    pub abandoned_count: usize,
    /// Number of descendant operations that were reparented onto the root
    /// of the abandoned range.
    pub rewritten_count: usize,
    /// `False` if the abandon was a no-op (nothing was actually
    /// unreachable/rewritten), matching `jj op abandon`'s own "Nothing
    /// changed." case.
    pub changed: bool,
}

/// `jj op abandon <operation>` equivalent: prunes the operation (or, with
/// `"root..head"` syntax -- either side may be omitted, meaning the
/// repo's root operation / the current head operations respectively -- a
/// contiguous range of operations) from the op log, reparenting descendant
/// operations onto the range's root so history stays connected. Distinct
/// from `undo`/`redo`/`restore_operation` (all `Transaction` methods that
/// create a *new* operation reverting/copying state) -- this edits the op
/// log itself and takes no `Transaction`, mirroring `reparent_range`
/// (`jj_lib::op_walk`) being a `RepoLoader`/`OpStore`-level primitive, not
/// a `MutableRepo` one.
///
/// Raises if `operation` resolves to (or its range includes) one of the
/// repo's current head operations, or (for the single-operation form) the
/// root operation or a merge operation -- same restrictions `jj op abandon`
/// itself enforces.
pub fn op_abandon(
    workspace: &mut jj_lib::workspace::Workspace,
    operation: &str,
) -> PyResult<PyOpAbandonStats> {
    let repo_loader = workspace.repo_loader();
    let op_store = repo_loader.op_store().clone();
    let op_heads_store = repo_loader.op_heads_store().clone();

    let current_head_ops = pollster::block_on(op_walk::get_current_head_ops(
        &op_store,
        op_heads_store.as_ref(),
    ))
    .map_err(map_py_err)?;
    let resolve_op = |op_str: &str| {
        pollster::block_on(op_walk::resolve_op_at(&op_store, &current_head_ops, op_str))
    };

    let (abandon_root_op, abandon_head_ops) =
        if let Some((root_str, head_str)) = operation.split_once("..") {
            let root_op = if root_str.is_empty() {
                pollster::block_on(workspace.repo_loader().root_operation())
            } else {
                resolve_op(root_str).map_err(map_py_err)?
            };
            let head_ops = if head_str.is_empty() {
                current_head_ops.clone()
            } else {
                vec![resolve_op(head_str).map_err(map_py_err)?]
            };
            (root_op, head_ops)
        } else {
            let op = resolve_op(operation).map_err(map_py_err)?;
            let parent_ops = pollster::block_on(op.parents()).map_err(map_py_err)?;
            let parent_op = match parent_ops.len() {
                0 => return Err(JjError::new_err("cannot abandon the root operation")),
                1 => parent_ops.into_iter().next().unwrap(),
                _ => return Err(JjError::new_err("cannot abandon a merge operation")),
            };
            (parent_op, vec![op])
        };

    if let Some(op) = abandon_head_ops
        .iter()
        .find(|op| current_head_ops.contains(op))
    {
        return Err(JjError::new_err(format!(
            "cannot abandon the current operation {}",
            op.id().hex()
        )));
    }

    let stats = pollster::block_on(op_walk::reparent_range(
        op_store.as_ref(),
        &abandon_head_ops,
        &current_head_ops,
        &abandon_root_op,
    ))
    .map_err(map_py_err)?;

    let reparented: Vec<(&Operation, &OperationId)> = current_head_ops
        .iter()
        .zip(stats.new_head_ids.iter())
        .collect();
    let changed = reparented.iter().any(|(old, new_id)| old.id() != *new_id);

    if changed {
        for (old, new_id) in &reparented {
            if old.id() != *new_id {
                pollster::block_on(
                    op_heads_store.update_op_heads(std::slice::from_ref(old.id()), new_id),
                )
                .map_err(map_py_err)?;
            }
        }
        let mut locked_ws =
            pollster::block_on(workspace.start_working_copy_mutation()).map_err(map_py_err)?;
        let old_op_id = locked_ws.locked_wc().old_operation_id().clone();
        if let Some((_, new_id)) = reparented.iter().find(|(old, _)| *old.id() == old_op_id) {
            pollster::block_on(locked_ws.finish((*new_id).clone())).map_err(map_py_err)?;
        }
    }

    Ok(PyOpAbandonStats {
        abandoned_count: stats.unreachable_count,
        rewritten_count: stats.rewritten_count,
        changed,
    })
}

fn parse_what(what: Option<Vec<String>>) -> PyResult<(bool, bool)> {
    let entries = what.unwrap_or_else(|| vec!["repo".to_string(), "remote_tracking".to_string()]);
    let mut restore_repo = false;
    let mut restore_remote_tracking = false;
    for entry in entries {
        match entry.as_str() {
            "repo" => restore_repo = true,
            "remote_tracking" => restore_remote_tracking = true,
            other => {
                return Err(JjError::new_err(format!(
                    "unknown `what` entry `{other}` (expected \"repo\" and/or \
                     \"remote_tracking\")"
                )));
            }
        }
    }
    Ok((restore_repo, restore_remote_tracking))
}

/// Restores only the portions of `target_view` selected by
/// `restore_repo`/`restore_remote_tracking`; everything else is left as
/// `current_view` already has it. Mirrors jj's own (`cli`-crate)
/// `view_with_desired_portions_restored`, used by both `jj undo` and
/// `jj op restore`, exactly -- reimplemented here since that function
/// itself is pure logic on public `jj_lib::op_store::View` fields, not
/// actually tied to anything `cli`-specific.
fn view_with_desired_portions_restored(
    target_view: &op_store::View,
    current_view: &op_store::View,
    restore_repo: bool,
    restore_remote_tracking: bool,
) -> op_store::View {
    let repo_source = if restore_repo {
        target_view
    } else {
        current_view
    };
    let remote_source = if restore_remote_tracking {
        target_view
    } else {
        current_view
    };
    op_store::View {
        head_ids: repo_source.head_ids.clone(),
        local_bookmarks: repo_source.local_bookmarks.clone(),
        local_tags: repo_source.local_tags.clone(),
        remote_views: remote_source.remote_views.clone(),
        git_refs: current_view.git_refs.clone(),
        git_head: current_view.git_head.clone(),
        wc_commit_ids: repo_source.wc_commit_ids.clone(),
    }
}

/// `jj op restore <target_op>` equivalent: makes the transaction's view
/// exactly `target_op`'s view (or a blend of it and the current view, per
/// `what` -- a list containing `"repo"` and/or `"remote_tracking"`,
/// defaulting to both). Does not commit -- call
/// `Transaction.commit(description)` afterward.
pub fn restore_operation(
    mut_repo: &mut MutableRepo,
    target_op: &PyOperation,
    what: Option<Vec<String>>,
) -> PyResult<()> {
    let (restore_repo, restore_remote_tracking) = parse_what(what)?;
    let target_view = pollster::block_on(target_op.0.view()).map_err(map_py_err)?;
    let current_view = mut_repo.base_repo().view().clone();
    let new_view = view_with_desired_portions_restored(
        target_view.store_view(),
        current_view.store_view(),
        restore_repo,
        restore_remote_tracking,
    );
    mut_repo.set_view(new_view);
    Ok(())
}

/// `jj op revert <target_op>` equivalent: undo one operation's effect
/// while keeping everything that happened after it.
///
/// This is not `restore_operation` with an older target. Restoring makes
/// the view *be* some past view, discarding later work; reverting merges
/// the target operation back out -- the repository at the target is
/// merged towards the repository at its parent, so only that one
/// operation's changes disappear.
///
/// Returns the description to pass to `Transaction.commit()`. Does not
/// commit.
pub fn revert_operation(
    mut_repo: &mut MutableRepo,
    target_op: &PyOperation,
    what: Option<Vec<String>>,
) -> PyResult<String> {
    let (restore_repo, restore_remote_tracking) = parse_what(what)?;
    let parents = pollster::block_on(target_op.0.parents()).map_err(map_py_err)?;
    let target_parent = match <[Operation; 1]>::try_from(parents) {
        Ok([parent]) => parent,
        Err(parents) if parents.is_empty() => {
            return Err(JjError::new_err("cannot revert the root operation"));
        }
        Err(_) => {
            return Err(JjError::new_err("cannot revert a merge operation"));
        }
    };

    let loader = mut_repo.base_repo().loader().clone();
    let repo_at_target =
        pollster::block_on(loader.load_at(&target_op.0)).map_err(map_py_err)?;
    let repo_at_parent =
        pollster::block_on(loader.load_at(&target_parent)).map_err(map_py_err)?;
    pollster::block_on(mut_repo.merge(&repo_at_target, &repo_at_parent))
        .map_err(map_py_err)?;

    let merged_view = mut_repo.view().store_view().clone();
    let base_view = mut_repo.base_repo().view().store_view().clone();
    let new_view = view_with_desired_portions_restored(
        &merged_view,
        &base_view,
        restore_repo,
        restore_remote_tracking,
    );
    mut_repo.set_view(new_view);

    Ok(format!("revert operation {}", target_op.0.id().hex()))
}

/// If `op`'s description matches `{prefix}{hex id}`, loads and returns the
/// operation that hex id refers to.
fn resolve_restore_target(
    loader: &jj_lib::repo::RepoLoader,
    op: &Operation,
    prefix: &str,
) -> PyResult<Option<Operation>> {
    let Some(hex) = op.metadata().description.strip_prefix(prefix) else {
        return Ok(None);
    };
    let id = OperationId::try_from_hex(hex).ok_or_else(|| {
        JjError::new_err("failed to parse operation id embedded in undo/redo-stack description")
    })?;
    let target = pollster::block_on(loader.load_operation(&id)).map_err(map_py_err)?;
    Ok(Some(target))
}

/// `jj undo` equivalent. Walks jj's own undo-stack-jumping rules (see
/// `cli/src/commands/undo.rs`) to determine what to actually restore to,
/// so repeated `undo()` calls behave like repeated `jj undo` (going
/// further back each time) rather than toggling between two states.
///
/// Returns `(undone_op, restored_to_op, description)`. Pass `description`
/// to `Transaction.commit()` unchanged -- it embeds `restored_to_op`'s id
/// in the exact format future `undo()`/`redo()` calls look for, so the
/// stack-jumping logic keeps working across multiple undo/redo calls. Does
/// not commit -- call `Transaction.commit(description)` afterward.
///
/// Raises `JjError` if there's nothing to undo (already at the root
/// operation) or the current operation is a merge of concurrent operations
/// (ambiguous what "undo" should mean there -- use `restore_operation`
/// instead, same as real jj recommends).
pub fn undo(mut_repo: &mut MutableRepo) -> PyResult<(PyOperation, PyOperation, String)> {
    let loader = mut_repo.base_repo().loader().clone();
    let mut target_op = mut_repo.base_repo().operation().clone();

    if let Some(op) = resolve_restore_target(&loader, &target_op, UNDO_OP_DESC_PREFIX)? {
        target_op = op;
    }

    let parents = pollster::block_on(target_op.parents()).map_err(map_py_err)?;
    let mut target_op_parent = match <[Operation; 1]>::try_from(parents) {
        Ok([parent]) => parent,
        Err(parents) if parents.is_empty() => {
            return Err(JjError::new_err("cannot undo the root operation"));
        }
        Err(_) => {
            return Err(JjError::new_err(
                "cannot undo a merge of concurrent operations -- use restore_operation instead",
            ));
        }
    };

    if let Some(op) = resolve_restore_target(&loader, &target_op_parent, UNDO_OP_DESC_PREFIX)? {
        target_op_parent = op;
    }

    let target_view = pollster::block_on(target_op_parent.view()).map_err(map_py_err)?;
    let current_view = mut_repo.base_repo().view().clone();
    let new_view = view_with_desired_portions_restored(
        target_view.store_view(),
        current_view.store_view(),
        true,
        true,
    );
    mut_repo.set_view(new_view);

    let description = format!("{UNDO_OP_DESC_PREFIX}{}", target_op_parent.id().hex());
    Ok((
        PyOperation(target_op),
        PyOperation(target_op_parent),
        description,
    ))
}

/// `jj redo` equivalent, the complement of `undo()`. See `undo()`'s docs
/// for the return shape and the undo/redo-stack-jumping rationale.
///
/// Raises `JjError` if the current operation isn't an undo (nothing to
/// redo).
pub fn redo(mut_repo: &mut MutableRepo) -> PyResult<(PyOperation, PyOperation, String)> {
    let loader = mut_repo.base_repo().loader().clone();
    let mut target_op = mut_repo.base_repo().operation().clone();

    if let Some(op) = resolve_restore_target(&loader, &target_op, REDO_OP_DESC_PREFIX)? {
        target_op = op;
    }

    if !target_op
        .metadata()
        .description
        .starts_with(UNDO_OP_DESC_PREFIX)
    {
        return Err(JjError::new_err("nothing to redo"));
    }

    let parents = pollster::block_on(target_op.parents()).map_err(map_py_err)?;
    let mut target_op_parent = match <[Operation; 1]>::try_from(parents) {
        Ok([parent]) => parent,
        Err(_) => {
            return Err(JjError::new_err(
                "undo operation should have exactly one parent",
            ));
        }
    };

    if let Some(op) = resolve_restore_target(&loader, &target_op_parent, REDO_OP_DESC_PREFIX)? {
        target_op_parent = op;
    }

    let target_view = pollster::block_on(target_op_parent.view()).map_err(map_py_err)?;
    let current_view = mut_repo.base_repo().view().clone();
    let new_view = view_with_desired_portions_restored(
        target_view.store_view(),
        current_view.store_view(),
        true,
        true,
    );
    mut_repo.set_view(new_view);

    let description = format!("{REDO_OP_DESC_PREFIX}{}", target_op_parent.id().hex());
    Ok((
        PyOperation(target_op),
        PyOperation(target_op_parent),
        description,
    ))
}
