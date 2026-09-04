//! `jj util gc`: backend garbage collection.
//!
//! Two stores hold garbage, and both are swept. The operation store
//! drops operations no longer reachable from the current head, and the
//! commit store drops objects no commit in the index refers to. What
//! "drop" means is up to the backend -- the Git backend runs `git gc`.
//!
//! Both take a cutoff and keep anything newer, because an object written
//! by a concurrent process may not be referenced yet.

use std::slice;
use std::time::{Duration, SystemTime};

use pyo3::prelude::*;

use jj_lib::repo::Repo as _;

use crate::commit::PyReadonlyRepo;
use crate::errors::{map_backend_err, map_py_err};

/// Collects garbage in both of the repo's stores.
///
/// `max_age_secs` is the cutoff: anything written less than that many
/// seconds ago survives, whether or not it is reachable. `jj util gc`
/// defaults to two weeks and `--expire=now` passes 0.
///
/// This sweeps from the repo's *own* operation. Loading a repo at a past
/// operation and collecting from there would delete everything the newer
/// operations added, so `jj` refuses that outright; the caller has to
/// make the same check, since a repo cannot tell here whether it is at
/// the head.
pub fn gc(repo: &PyReadonlyRepo, max_age_secs: f64) -> PyResult<()> {
    let keep_newer = SystemTime::now() - Duration::from_secs_f64(max_age_secs.max(0.0));
    let inner = repo.inner.as_ref();
    pollster::block_on(
        inner
            .op_store()
            .gc(slice::from_ref(inner.op_id()), keep_newer),
    )
    .map_err(map_py_err)?;
    inner
        .store()
        .gc(inner.index(), keep_newer)
        .map_err(map_backend_err)?;
    Ok(())
}
