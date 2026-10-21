"""Tests for ReadonlyRepo.gc() -- `jj util gc`.

Garbage collection removes what nothing refers to, so its effect is by
definition invisible through the repo's own API. These tests hold it to
what can be checked: it runs, and the repo still works afterwards.
"""

import pytest

import pyjj


def test_gc_runs_and_leaves_the_repo_usable(repo, settings, wc_commit):
    repo.gc(0)
    assert repo.get_commit(wc_commit.id).id.hex() == wc_commit.id.hex()


def test_gc_default_keeps_everything_recent(repo, settings, wc_commit):
    """Two weeks of grace covers every object a fresh repo holds."""
    repo.gc(14 * 86400)
    assert repo.get_commit(wc_commit.id).id.hex() == wc_commit.id.hex()


def test_gc_keeps_reachable_commits(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("keep me")
    kept = builder.write(repo)
    tx.set_wc_commit("default", kept.id)
    tx.rebase_descendants()
    repo = tx.commit("create")

    repo.gc(0)
    assert repo.get_commit(kept.id).description.strip() == "keep me"


def test_gc_negative_age_is_clamped(repo, settings, wc_commit):
    """A negative cutoff would be a time in the future; it means 'now'."""
    repo.gc(-1)
    assert repo.get_commit(wc_commit.id).id.hex() == wc_commit.id.hex()


def test_gc_refuses_a_repo_behind_the_head_operation(repo, settings):
    repo.start_transaction(settings).commit("move the head on")
    with pytest.raises(pyjj.JjError, match="non-head operation"):
        repo.gc(0)


def test_gc_default_cutoff_is_two_weeks(repo, settings, wc_commit):
    repo.gc()
    assert repo.get_commit(wc_commit.id).id == wc_commit.id


@pytest.mark.parametrize("age", [float("inf"), 1e20, float("nan")])
def test_gc_rejects_a_cutoff_no_clock_can_hold(repo, age):
    with pytest.raises(ValueError, match="max_age_secs"):
        repo.gc(age)
