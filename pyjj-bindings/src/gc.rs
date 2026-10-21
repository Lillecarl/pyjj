//! `jj util gc`: backend garbage collection.
//!
//! Two stores hold garbage and both are swept. The operation store
//! drops operations no longer reachable from the current head, and the
//! commit store drops objects no commit in the index refers to. What
//! "drop" means is up to the backend -- the Git backend runs `git gc`.
//!
//! Both take a cutoff and keep anything newer, because an object written
//! by a concurrent process may not be referenced yet.
//!
//! This mirrors `cli/src/commands/util/gc.rs`: the op-store sweep always
//! runs, and the commit-store sweep runs only when the store is git-backed
//! (`jj_lib::git::get_git_backend`); other backends have nothing to sweep.

use std::slice;
use std::time::{Duration, SystemTime};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use jj_lib::op_walk::get_current_head_ops;
use jj_lib::repo::Repo as _;

use crate::commit::PyReadonlyRepo;
use crate::errors::{JjError, map_backend_err, map_py_err};

/// Collects garbage in both of the repo's stores.
///
/// `max_age_secs` is the cutoff: anything written less than that many
/// seconds ago survives, whether or not it is reachable. `jj util gc`
/// defaults to two weeks and `--expire=now` passes 0.
///
/// Refuses unless the repo is at the single head operation, as `jj`
/// does: sweeping from a past operation deletes everything the newer
/// operations added, the head among them.
pub fn gc(repo: &PyReadonlyRepo, max_age_secs: f64) -> PyResult<()> {
    // Not `f64::max`: it maps NaN to 0, which is "expire now".
    let age = if max_age_secs < 0.0 { 0.0 } else { max_age_secs };
    let keep_newer = Duration::try_from_secs_f64(age)
        .ok()
        .and_then(|age| SystemTime::now().checked_sub(age))
        .ok_or_else(|| PyValueError::new_err(format!("max_age_secs out of range: {max_age_secs}")))?;
    let inner = repo.inner.as_ref();
    let heads = pollster::block_on(get_current_head_ops(
        inner.op_store(),
        inner.op_heads_store().as_ref(),
    ))
    .map_err(map_py_err)?;
    if !matches!(heads.as_slice(), [head] if head.id() == inner.op_id()) {
        return Err(JjError::new_err(
            "Cannot garbage collect from a non-head operation",
        ));
    }
    pollster::block_on(
        inner
            .op_store()
            .gc(slice::from_ref(inner.op_id()), keep_newer),
    )
    .map_err(map_py_err)?;
    if let Ok(git_backend) = jj_lib::git::get_git_backend(inner.store()) {
        git_backend
            .gc(inner.index(), keep_newer)
            .map_err(map_backend_err)?;
    }
    Ok(())
}
