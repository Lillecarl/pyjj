"""Tests for RunPool/RunSlot and Transaction.run_rewrite -- `jj run`.

A slot is a checkout with no workspace and no view entry, so these tests
work directly on the files it puts on disk and on the tree id it hands
back afterwards.
"""

import os
from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def committed(workspace, repo, settings, wc_commit):
    """A commit holding `a.txt` and `dir/b.txt`, plus the repo it is in."""
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_bytes(b"a\n")
    (root / "dir").mkdir()
    (root / "dir" / "b.txt").write_bytes(b"b\n")
    repo, _stats = workspace.snapshot(settings)
    view = repo.view()
    wc_hex = next(iter(view.values()))
    return repo, repo.get_commit(pyjj.CommitId(wc_hex))


def test_slot_checks_the_commit_tree_out(workspace, settings, committed):
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    try:
        root = Path(slot.working_copy_dir)
        assert (root / "a.txt").read_bytes() == b"a\n"
        assert (root / "dir" / "b.txt").read_bytes() == b"b\n"
    finally:
        slot.discard()


def test_slot_lives_under_the_run_directory(workspace, settings, committed):
    """Slots go in `.jj/run/default/<n>`, never inside `.jj/repo`."""
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    try:
        expected = os.path.join(
            os.path.dirname(workspace.repo_path), "run", "default", "1",
            "working_copy")
        assert slot.working_copy_dir == expected
    finally:
        slot.discard()


def test_finish_reports_an_untouched_tree_as_clean(workspace, settings, committed):
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    dirty, tree_id = slot.finish(True)
    assert dirty is False
    assert tree_id is not None


def test_finish_returns_the_tree_the_edit_produced(workspace, settings, committed):
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    (Path(slot.working_copy_dir) / "a.txt").write_bytes(b"edited\n")
    dirty, tree_id = slot.finish(True)
    assert dirty is True
    assert tree_id is not None


def test_a_failed_command_gets_no_tree(workspace, settings, committed):
    """`success=False` is how the caller says the command failed. Its
    output must not reach a commit, so no tree comes back."""
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    (Path(slot.working_copy_dir) / "a.txt").write_bytes(b"edited\n")
    _dirty, tree_id = slot.finish(False)
    assert tree_id is None


def test_a_released_slot_cannot_be_finished_again(workspace, settings, committed):
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    slot.discard()
    with pytest.raises(pyjj.JjError):
        slot.finish(True)


def test_the_pool_reuses_a_slot_after_release(workspace, settings, committed):
    """One slot serves every commit in turn, which is what makes a build
    tree survive from one revision to the next."""
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    first = pool.acquire(commit)
    path = first.working_copy_dir
    first.discard()
    second = pool.acquire(commit)
    try:
        assert second.working_copy_dir == path
    finally:
        second.discard()


def test_clean_wipes_files_the_last_job_left(workspace, settings, committed):
    """A file the last job left survives a normal acquisition, because
    the slot is reused, and does not survive a `clean` one."""
    _repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    artifact = Path(slot.working_copy_dir) / "artifact.o"
    artifact.write_bytes(b"built\n")
    slot.finish(True)

    clean_pool = pyjj.RunPool(workspace.repo_path, 1, True)
    slot = clean_pool.acquire(commit)
    try:
        assert not artifact.exists()
    finally:
        slot.discard()


def test_pool_size_must_be_positive(workspace):
    with pytest.raises(pyjj.JjError):
        pyjj.RunPool(workspace.repo_path, 0)


def test_run_rewrite_puts_the_tree_on_the_commit(workspace, settings, committed):
    """The whole loop: check out, edit, snapshot, write it back."""
    repo, commit = committed
    pool = pyjj.RunPool(workspace.repo_path, 1)
    slot = pool.acquire(commit)
    (Path(slot.working_copy_dir) / "a.txt").write_bytes(b"edited\n")
    _dirty, tree_id = slot.finish(True)

    tx = repo.start_transaction(settings)
    count, reparented = tx.run_rewrite([commit.id], {commit.id.hex(): tree_id})
    assert (count, reparented) == (1, 0)
    tx.rebase_descendants()
    repo = tx.commit("run: rewrite 1 commits")

    view = repo.view()
    rewritten = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))
    assert rewritten.id.hex() != commit.id.hex()
    assert rewritten.change_id.hex() == commit.change_id.hex()


def test_run_rewrite_without_any_tree_changes_nothing(workspace, settings, committed):
    repo, commit = committed
    tx = repo.start_transaction(settings)
    count, reparented = tx.run_rewrite([commit.id], {})
    assert (count, reparented) == (0, 0)


def test_run_rewrite_rejects_an_unreadable_commit_id(workspace, settings, committed):
    repo, commit = committed
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.run_rewrite([commit.id], {"nothex": pyjj.TreeId("00" * 20)})
