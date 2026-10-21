"""`*_async` siblings for the blocking methods of `ReadonlyRepo`, `Commit`
and `Workspace`.

Each sibling runs the sync method in `anyio.to_thread.run_sync`. The Rust
side releases the GIL for the whole call, so the event loop keeps running,
on asyncio and trio alike. `run_sync` waits for the thread on cancellation,
so a cancelled call never leaves a working-copy lock half held.

`Transaction` has no async API. jj_lib's `MutableRepo` is not `Send`, so
`PyTransaction` is `unsendable` and touching it from a worker thread panics.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Final

import anyio.to_thread
from pyjj_bindings import Commit, ReadonlyRepo, Workspace

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_INSTANCE_METHODS: Final[dict[type, tuple[str, ...]]] = {
    ReadonlyRepo: (
        "get_commit",
        "revset",
        "find_divergent_changes",
        "log_graph",
        "commits_graph",
        "evolution_log",
        "evolution_graph",
        "interdiff_files",
        "materialize_merge",
        "walk_revs_count",
        "interdiff",
        "resolve_single",
        "shortest_commit_id_prefix_len",
        "shortest_change_id_prefix_len",
        "operation_log",
        "load_operation",
        "load_at_operation",
        "gc",
        "merge_operations",
        "operation_diff",
    ),
    Commit: (
        "conflicted_paths",
        "diff_from_parents",
        "is_hidden",
        "is_divergent",
        "change_offset",
        "is_empty",
        "is_discardable",
        "diff",
        "diff_stats",
        "git_diff",
        "diff_with_copies",
        "read_file",
        "parent_contents",
        "file_exists",
        "list_files",
        "is_executable",
        "file_kind",
        "match_filesets",
        "materialize_conflict",
        "annotate",
    ),
    Workspace: (
        "snapshot",
        "untrack_paths",
        "check_out",
        "reset",
        "op_abandon",
        "update_stale",
        "set_sparse_patterns",
        "add_workspace",
        "forget_workspaces",
        "rename_workspace",
        "load_at_head",
        "is_colocated",
        "create_git_worktree",
        "unlink_git_worktree",
    ),
}
_STATIC_METHODS: Final[dict[type, tuple[str, ...]]] = {
    Workspace: ("clone_git",),
}


def _to_thread(
    func: Callable[..., Any], cls: type, name: str
) -> Callable[..., Coroutine[Any, Any, Any]]:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs))

    wrapper.__name__ = f"{name}_async"
    wrapper.__qualname__ = f"{cls.__name__}.{name}_async"
    wrapper.__doc__ = f"Async sibling of `{cls.__name__}.{name}()`, run in a worker thread."
    return wrapper


def _install() -> None:
    for cls, names in _INSTANCE_METHODS.items():
        for name in names:
            setattr(cls, f"{name}_async", _to_thread(getattr(cls, name), cls, name))
    for cls, names in _STATIC_METHODS.items():
        for name in names:
            setattr(cls, f"{name}_async", staticmethod(_to_thread(getattr(cls, name), cls, name)))


_install()
