"""Tests for pyjj's async surface.

`ReadonlyRepo`/`Commit` get real `pyo3-async-runtimes`/tokio integration
(native, defined in `pyjj_bindings`); `Workspace` gets `anyio.to_thread`
wrapping with genuine GIL release (defined in `pyjj._async`); `Transaction`
intentionally has no async API at all (see `pyjj/pyjj/_async.py`'s
docstring for why). Tests are plain `async def` -- `anyio_mode = "auto"`
in `pyproject.toml` runs them via anyio's own pytest plugin, no
`pytest-asyncio` dependency and no manual `asyncio.run()` per test.
"""

import subprocess
from pathlib import Path

import anyio
import pytest

import pyjj


@pytest.fixture
def bare_remote(tmp_path_factory):
    """A minimal bare git repo with one commit on its default branch --
    just enough for `clone_git`/`clone_git_async` to have something to
    fetch. Same no-network approach as test_git_clone.py's fixture.
    """
    remote_dir = tmp_path_factory.mktemp("remote") / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_dir)], check=True, capture_output=True
    )
    seed_dir = tmp_path_factory.mktemp("seed")
    subprocess.run(["git", "init", "-b", "main", str(seed_dir)], check=True, capture_output=True)
    (seed_dir / "README.md").write_text("hello\n")
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", "add", "README.md"],
        cwd=seed_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-m", "seed"],
        cwd=seed_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", str(remote_dir), "main"], cwd=seed_dir, check=True, capture_output=True
    )
    return remote_dir


def test_transaction_has_no_async_methods(repo, settings):
    tx = repo.start_transaction(settings)
    assert not hasattr(tx, "commit_async")
    assert not hasattr(tx, "rebase_descendants_async")


def test_commit_builder_has_no_async_methods(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    assert not hasattr(builder, "write_async")


async def test_readonly_repo_async_methods_match_sync(repo, settings, wc_commit):
    commit = await repo.get_commit_async(wc_commit.id)
    assert commit.id == wc_commit.id

    commits = await repo.revset_async(settings, "@")
    assert commits == repo.revset(settings, "@")

    resolved = await repo.resolve_single_async(settings, "@")
    assert resolved.id == wc_commit.id

    ops = await repo.operation_log_async()
    assert ops == repo.operation_log()

    op = repo.operation
    loaded = await repo.load_operation_async(op.id)
    assert loaded.id == op.id

    at_op = await repo.load_at_operation_async(op)
    assert at_op.operation.id == op.id


async def test_commit_async_methods_match_sync(workspace, repo, settings, wc_commit):
    Path(workspace.workspace_root, "a.txt").write_text("hello\n")
    new_repo, _stats = workspace.snapshot(settings)
    new_wc = new_repo.resolve_single(settings, "@")

    assert await new_wc.is_empty_async(new_repo) == new_wc.is_empty(new_repo)
    assert await new_wc.is_discardable_async(new_repo) == new_wc.is_discardable(new_repo)

    entries = await wc_commit.diff_async(new_wc)
    assert [e.path for e in entries] == [e.path for e in wc_commit.diff(new_wc)]

    entries_copies = await wc_commit.diff_with_copies_async(new_wc)
    assert [e.path for e in entries_copies] == [
        e.path for e in wc_commit.diff_with_copies(new_wc)
    ]

    content = await new_wc.read_file_async("a.txt")
    assert content == b"hello\n"

    assert await new_wc.file_exists_async("a.txt") is True
    assert await new_wc.file_exists_async("nonexistent.txt") is False

    assert await new_wc.is_executable_async("a.txt") == new_wc.is_executable("a.txt")
    assert await new_wc.list_files_async() == new_wc.list_files()

    lines = await new_wc.annotate_async(new_repo, "a.txt")
    assert [(l.commit_id, l.line) for l in lines] == [
        (l.commit_id, l.line) for l in new_wc.annotate(new_repo, "a.txt")
    ]


async def test_workspace_snapshot_async_matches_sync(workspace, settings):
    Path(workspace.workspace_root, "b.txt").write_text("world\n")
    new_repo, stats = await workspace.snapshot_async(settings)
    assert "untracked_paths" in stats
    wc = new_repo.resolve_single(settings, "@")
    assert wc.read_file("b.txt") == b"world\n"


async def test_workspace_check_out_and_update_stale_async(workspace, repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("child")
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    new_repo = tx.commit("advance wc")

    stats = await workspace.check_out_async(new_repo, child)
    assert isinstance(stats, dict)
    assert new_repo.resolve_single(settings, "@").id == child.id

    fresh = workspace.load_at_head()
    result = await workspace.update_stale_async(fresh)
    assert result is None  # already up to date


async def test_workspace_sparse_patterns_async(workspace, settings):
    Path(workspace.workspace_root, "dir").mkdir()
    Path(workspace.workspace_root, "dir", "b.txt").write_text("b\n")
    workspace.snapshot(settings)

    stats = await workspace.set_sparse_patterns_async(["dir"])
    assert isinstance(stats, dict)
    assert workspace.sparse_patterns() == ["dir"]
    await workspace.set_sparse_patterns_async([""])
    assert workspace.sparse_patterns() == [""]


async def test_workspace_add_and_forget_and_rename_async(workspace, settings, tmp_path):
    second_dir = tmp_path.parent / (tmp_path.name + "-second")
    second_dir.mkdir()
    second_ws, second_repo = await workspace.add_workspace_async(settings, str(second_dir))
    assert second_ws.workspace_name == second_dir.name
    assert second_dir.name in second_repo.view()

    forgotten_repo = await workspace.forget_workspaces_async(
        settings, [second_ws.workspace_name]
    )
    assert second_ws.workspace_name not in forgotten_repo.view()

    renamed_repo = await workspace.rename_workspace_async(settings, "renamed")
    assert workspace.workspace_name == "renamed"
    assert "renamed" in renamed_repo.view()


async def test_workspace_load_at_head_async(workspace):
    repo = await workspace.load_at_head_async()
    assert repo is not None


async def test_workspace_clone_git_async(bare_remote, settings, tmp_path):
    dest_dir = tmp_path / "clone"
    _ws, cloned_repo = await pyjj.Workspace.clone_git_async(
        settings, str(bare_remote), str(dest_dir)
    )
    assert cloned_repo.git_remotes() == ["origin"]


async def test_workspace_async_concurrency_frees_event_loop(workspace, settings):
    """The whole point of Workspace's `_async` methods over calling the sync
    ones directly: the Rust side releases the GIL, so a slow snapshot
    shouldn't stall other coroutines. A tight heartbeat's max gap staying
    close to its sleep interval is the signal that actually happened.
    """
    import time

    for i in range(500):
        Path(workspace.workspace_root, f"file{i}.txt").write_text("x" * 200)

    heartbeats = []

    async def heartbeat():
        for _ in range(15):
            heartbeats.append(time.monotonic())
            await anyio.sleep(0.01)

    async with anyio.create_task_group() as tg:
        tg.start_soon(heartbeat)
        tg.start_soon(workspace.snapshot_async, settings)
    gaps = [b - a for a, b in zip(heartbeats, heartbeats[1:])]
    assert max(gaps) < 0.2, f"event loop was blocked: {max(gaps)}"
