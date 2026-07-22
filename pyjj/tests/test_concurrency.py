"""Concurrency/locking tests, mirroring the themes of jj's own
test_concurrent_operations.rs/test_bad_locking.rs -- but scoped to what
pyjj actually exposes: (1) genuine multi-thread pressure on a single
Workspace via its asyncio `_async` methods (the Mutex<Workspace> fix),
and (2) jj_lib's own divergent-operation handling when two Transactions
are started from the same base ReadonlyRepo (no process-level locking
involved here -- just two live Transaction objects in one process).
"""

import asyncio
from pathlib import Path

import pyjj


def test_two_transactions_from_same_base_both_commit_independently(workspace, repo, settings, wc_commit):
    tx1 = repo.start_transaction(settings)
    tx2 = repo.start_transaction(settings)

    b1 = tx1.new_commit(settings, [wc_commit.id])
    b1.set_description("from tx1")
    c1 = b1.write(repo)
    tx1.set_wc_commit("default", c1.id)
    repo_after_1 = tx1.commit("tx1 op")

    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("from tx2")
    c2 = b2.write(repo)
    tx2.set_wc_commit("default", c2.id)
    repo_after_2 = tx2.commit("tx2 op")

    # Each transaction's own resulting repo reflects only its own change --
    # committing tx2 must not have silently mutated repo_after_1's view.
    assert repo_after_1.view()["default"] == c1.id.hex()
    assert repo_after_2.view()["default"] == c2.id.hex()


def test_divergent_operations_reconcile_without_raising(workspace, repo, settings, wc_commit):
    tx1 = repo.start_transaction(settings)
    tx2 = repo.start_transaction(settings)

    b1 = tx1.new_commit(settings, [wc_commit.id])
    b1.set_description("from tx1")
    c1 = b1.write(repo)
    tx1.set_wc_commit("default", c1.id)
    tx1.commit("tx1 op")

    b2 = tx2.new_commit(settings, [wc_commit.id])
    b2.set_description("from tx2")
    c2 = b2.write(repo)
    tx2.set_wc_commit("default", c2.id)
    tx2.commit("tx2 op")

    # Two divergent op heads now exist. Loading at head must reconcile them
    # (jj_lib's own merge_operations logic) rather than raising -- which of
    # the two wc commits wins is an implementation detail of that merge, not
    # a contract pyjj should pin down here.
    merged_repo = workspace.load_at_head()
    merged_wc_id = merged_repo.view()["default"]
    assert merged_wc_id in {c1.id.hex(), c2.id.hex()}


def test_concurrent_snapshot_async_calls_serialize_safely(workspace, repo, settings):
    root = Path(workspace.workspace_root)

    async def write_and_snapshot(i):
        (root / f"f{i}.txt").write_text(f"{i}\n")
        return await workspace.snapshot_async(settings)

    async def run():
        return await asyncio.gather(*(write_and_snapshot(i) for i in range(8)))

    results = asyncio.run(run())
    assert len(results) == 8

    final_repo = workspace.load_at_head()
    wc = final_repo.get_commit(pyjj.CommitId(final_repo.view()["default"]))
    for i in range(8):
        assert wc.file_exists(f"f{i}.txt")
