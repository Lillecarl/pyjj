"""`anyio.to_thread.run_sync`-based async siblings for `Workspace`.

Unlike `ReadonlyRepo`/`Commit` (native `pyo3-async-runtimes`/tokio
integration, see `pyjj_bindings`), `Workspace` can't get real tokio-based
async: jj_lib's `Workspace` holds a `Box<dyn WorkingCopy>` (not `Sync`), so
its `_async` methods are implemented here in pure Python via
`anyio.to_thread.run_sync` instead. They *do* genuinely free the event loop
while running, though -- the Rust side releases the GIL (`Python::detach`)
for the duration of each call. anyio (not bare `asyncio.to_thread`) so
callers on any event loop anyio supports -- not just asyncio -- can await
these, matching the rest of the project's anyio-first convention.

`Transaction` has **no** async API at all, on purpose: its Rust side
(`PyTransaction`) is `#[pyclass(unsendable)]` because jj_lib's
`MutableRepo`/`Transaction` isn't even `Send` (it holds a `Box<dyn
MutableIndex>`, and that trait doesn't declare `Send`) -- there's no safe
way to move it to a worker thread at all, so `to_thread.run_sync` would
crash with a hard `unsendable` panic the instant it touched a Transaction
from any thread but the one that created it (confirmed empirically, not
just reasoned). Use `Transaction` synchronously -- it's fine to call its
methods inline inside an `async def`, they just won't yield to the event
loop while running, same as any other synchronous call would.

Every method wrapped here has both a sync (unchanged, pre-existing) and an
`_async` form; nothing is removed or renamed.
"""

import functools

import anyio.to_thread
from pyjj_bindings import Workspace

# Workspace methods that do real working-copy/backend I/O -- mirrors which
# Workspace methods got `Python::detach` wrapping on the Rust side.
_WORKSPACE_METHODS = (
    "snapshot",
    "check_out",
    "update_stale",
    "set_sparse_patterns",
    "add_workspace",
    "forget_workspaces",
    "rename_workspace",
    "load_at_head",
)
_WORKSPACE_STATIC_METHODS = ("clone_git",)


def _wrap_instance_method(func):
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(func, self, *args, **kwargs))

    return wrapper


def _wrap_static_method(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs))

    return staticmethod(wrapper)


def _install():
    for name in _WORKSPACE_METHODS:
        setattr(Workspace, f"{name}_async", _wrap_instance_method(getattr(Workspace, name)))
    for name in _WORKSPACE_STATIC_METHODS:
        setattr(Workspace, f"{name}_async", _wrap_static_method(getattr(Workspace, name)))


_install()
