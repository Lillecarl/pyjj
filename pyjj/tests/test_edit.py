"""Tests for Transaction.edit(): jj new <rev>/jj edit <rev>'s core semantic
of moving a workspace's wc pointer, mirroring lib/tests/test_mut_repo.rs's
test_edit_previous_empty/test_edit_previous_not_empty.
"""

import pyjj


def test_edit_abandons_previous_wc_if_discardable_and_orphaned(repo, settings, wc_commit):
    """Moving to an *unrelated* commit (not a descendant of the current wc)
    leaves the old wc commit an orphaned, empty, undescribed head -- edit()
    should abandon it, matching jj_lib's own test_edit_previous_empty.
    """
    root_id = pyjj.CommitId("0" * 40)

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [root_id])
    sibling = builder.write(repo)
    tx.edit("default", sibling)
    tx.rebase_descendants()
    new_repo = tx.commit("edit to sibling")

    heads = {c.id for c in new_repo.revset(settings, "heads(all())")}
    assert wc_commit.id not in heads


def test_edit_does_not_abandon_previous_wc_if_described(repo, settings, wc_commit):
    """Same as above, but the old wc commit has a description -- it's not
    discardable, so it must be kept. Mirrors test_edit_previous_not_empty.
    """
    root_id = pyjj.CommitId("0" * 40)
    tx0 = repo.start_transaction(settings)
    builder0 = tx0.rewrite_commit(settings, wc_commit)
    builder0.set_description("keep me")
    described = builder0.write(repo)
    tx0.edit("default", described)
    tx0.rebase_descendants()
    repo = tx0.commit("describe wc")
    described = repo.get_commit(described.id)

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [root_id])
    sibling = builder.write(repo)
    tx.edit("default", sibling)
    tx.rebase_descendants()
    new_repo = tx.commit("edit to sibling")

    heads = {c.id for c in new_repo.revset(settings, "heads(all())")}
    assert described.id in heads


def test_edit_does_not_abandon_when_advancing_to_a_child(repo, settings, wc_commit):
    """The everyday `jj new` case: advancing to a *child* of the current wc
    already makes the old wc non-head (it has a visible child now), so
    edit()'s abandon check doesn't fire -- matches real jj, which doesn't
    delete history just because you moved forward.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    child = builder.write(repo)
    tx.edit("default", child)
    new_repo = tx.commit("new")

    assert new_repo.view()["default"] == child.id.hex()
    assert new_repo.revset(settings, wc_commit.id.hex()) == [wc_commit]


def test_edit_registers_commit_as_a_repo_head(repo, settings, wc_commit):
    root_id = pyjj.CommitId("0" * 40)
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [root_id])
    sibling = builder.write(repo)
    tx.edit("default", sibling)
    tx.rebase_descendants()
    new_repo = tx.commit("edit")

    heads = {c.id for c in new_repo.revset(settings, "heads(all())")}
    assert sibling.id in heads
