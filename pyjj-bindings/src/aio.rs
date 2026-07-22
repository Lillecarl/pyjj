//! Helper for exposing genuinely-awaitable (`asyncio`-compatible) siblings
//! of existing sync methods, for the classes where it's actually sound.
//!
//! Only `ReadonlyRepo` and `Commit` get real `pyo3-async-runtimes`/tokio
//! integration (see `spawn_blocking_py` below) -- both wrap only `Send +
//! Sync` jj_lib data (`Arc<ReadonlyRepo>`, `Commit`), so an owned handle can
//! be safely moved onto a tokio worker thread. `Workspace` and
//! `Transaction`/`MutableRepo` cannot: jj_lib's `Workspace` holds a
//! `Box<dyn WorkingCopy>` (not `Sync`) and `MutableRepo` holds a `Box<dyn
//! MutableIndex>` (not even `Send`) -- both are trait-object erasure gaps
//! upstream, not something pyjj can safely paper over with an `unsafe impl
//! Send`/`Sync` without betting on jj_lib internals that aren't part of its
//! contract. Those two get `asyncio.to_thread`-based wrapping instead, in
//! the pure-Python `pyjj` package -- see `AGENTS.md`'s async section.
//!
//! jj_lib's own `async fn`s are not backed by real non-blocking I/O (they
//! wrap ordinary synchronous `std::fs`/`gix` calls, purely so independent
//! reads can be pipelined via `buffer_unordered`/`try_join_all` within one
//! call) -- so the work handed to `future_into_py` here always goes through
//! `tokio::task::spawn_blocking` rather than being awaited directly on a
//! shared runtime worker, which would otherwise risk stalling that worker
//! on blocking disk I/O.

use pyo3::prelude::*;

use crate::errors::JjError;

/// Runs `f` on tokio's blocking thread pool and bridges the result back as
/// a Python awaitable. `f` only needs to be `Send` for its captured data
/// (typically a cloned `Arc<ReadonlyRepo>` and owned argument values) --
/// nothing PyO3/GIL-bound needs to cross the thread boundary.
pub fn spawn_blocking_py<'py, F, T>(py: Python<'py>, f: F) -> PyResult<Bound<'py, PyAny>>
where
    F: FnOnce() -> PyResult<T> + Send + 'static,
    T: for<'p> IntoPyObject<'p> + Send + 'static,
{
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        match tokio::task::spawn_blocking(f).await {
            Ok(result) => result,
            Err(join_err) => Err(JjError::new_err(format!(
                "background task panicked: {join_err}"
            ))),
        }
    })
}
