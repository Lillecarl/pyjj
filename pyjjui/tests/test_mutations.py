"""Tests for mutations.py's sync (workspace, repo, settings, ...) -> ReadonlyRepo functions."""

from pyjjui import mutations

from . import testutils


def test_new_child_creates_and_checks_out_a_child(workspace, settings, seeded_repo):
    repo = seeded_repo
    parent = repo.resolve_single(settings, "@")

    new_repo = mutations.new_child(workspace, repo, settings, [parent])

    wc = new_repo.resolve_single(settings, "@")
    assert wc.id != parent.id
    assert wc.parent_ids == [parent.id]


def test_new_child_with_two_parents_creates_a_merge_commit(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    b = repo.resolve_single(settings, "description(exact:'B')")

    new_repo = mutations.new_child(workspace, repo, settings, [a, b])

    wc = new_repo.resolve_single(settings, "@")
    assert set(wc.parent_ids) == {a.id, b.id}


def test_edit_checks_out_an_existing_commit(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")

    new_repo = mutations.edit(workspace, repo, settings, a)

    assert new_repo.resolve_single(settings, "@").id == a.id


def test_describe_rewrites_the_description(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")

    new_repo = mutations.describe(workspace, repo, settings, a, "A renamed")

    renamed = new_repo.resolve_single(settings, "description(exact:'A renamed')")
    assert renamed.change_id == a.change_id


def test_describe_updates_the_working_copy_when_describing_it(workspace, settings, seeded_repo):
    repo = seeded_repo
    wc = repo.resolve_single(settings, "@")

    new_repo = mutations.describe(workspace, repo, settings, wc, "B renamed")

    new_wc = new_repo.resolve_single(settings, "@")
    assert new_wc.change_id == wc.change_id
    assert new_wc.description == "B renamed"


def test_abandon_removes_the_commit(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")

    new_repo = mutations.abandon(workspace, repo, settings, [a])

    assert new_repo.revset(settings, "description(exact:'A')") == []


def test_abandon_removes_multiple_commits_in_one_operation(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    b = repo.resolve_single(settings, "description(exact:'B')")

    new_repo = mutations.abandon(workspace, repo, settings, [a, b])

    assert new_repo.revset(settings, "description(exact:'A') | description(exact:'B')") == []


def test_rebase_onto_reparents_the_source_commit(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    b = repo.resolve_single(settings, "description(exact:'B')")
    # C branches off the same parent as A (root), independent of A/B.
    root = repo.get_commit(a.parent_ids[0])
    repo, c = testutils.new_child(workspace, repo, settings, root, "C")
    b = repo.get_commit(b.id)

    new_repo = mutations.rebase(
        workspace, repo, settings, [c], b, mode="onto", include_descendants=False
    )

    rebased_c = new_repo.revset(settings, "description(exact:'C')")[0]
    assert rebased_c.parent_ids == [b.id]


def test_rebase_after_splices_in_as_a_new_child(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    b = repo.resolve_single(settings, "description(exact:'B')")
    root = repo.get_commit(a.parent_ids[0])
    repo, c = testutils.new_child(workspace, repo, settings, root, "C")
    a = repo.get_commit(a.id)

    new_repo = mutations.rebase(
        workspace, repo, settings, [c], a, mode="after", include_descendants=False
    )

    rebased_c = new_repo.revset(settings, "description(exact:'C')")[0]
    rebased_b = new_repo.revset(settings, "description(exact:'B')")[0]
    assert rebased_c.parent_ids == [a.id]
    assert rebased_b.parent_ids == [rebased_c.id]


def test_rebase_before_splices_in_as_a_new_parent(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    root = repo.get_commit(a.parent_ids[0])
    repo, c = testutils.new_child(workspace, repo, settings, root, "C")
    a = repo.get_commit(a.id)

    new_repo = mutations.rebase(
        workspace, repo, settings, [c], a, mode="before", include_descendants=False
    )

    rebased_c = new_repo.revset(settings, "description(exact:'C')")[0]
    rebased_a = new_repo.revset(settings, "description(exact:'A')")[0]
    assert rebased_c.parent_ids == [root.id]
    assert rebased_a.parent_ids == [rebased_c.id]


def test_rebase_include_descendants_moves_the_whole_branch(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    b = repo.resolve_single(settings, "description(exact:'B')")
    root = repo.get_commit(a.parent_ids[0])
    repo, c = testutils.new_child(workspace, repo, settings, root, "C")
    repo, c_child = testutils.new_child(workspace, repo, settings, c, "C child")
    b = repo.get_commit(b.id)
    c = repo.get_commit(c.id)

    new_repo = mutations.rebase(
        workspace, repo, settings, [c], b, mode="onto", include_descendants=True
    )

    rebased_c = new_repo.revset(settings, "description(exact:'C')")[0]
    rebased_c_child = new_repo.revset(settings, "description(exact:'C child')")[0]
    assert rebased_c.parent_ids == [b.id]
    assert rebased_c_child.parent_ids == [rebased_c.id]


def test_set_bookmark_points_it_at_the_given_commit(workspace, settings, seeded_repo):
    repo = seeded_repo
    b = repo.resolve_single(settings, "description(exact:'B')")

    new_repo = mutations.set_bookmark(workspace, repo, settings, b, "release")

    bookmark = new_repo.get_bookmark("release")
    assert bookmark is not None
    assert bookmark.target_ids == [b.id]


def test_set_bookmark_does_not_move_the_working_copy(workspace, settings, seeded_repo):
    repo = seeded_repo
    wc = repo.resolve_single(settings, "@")
    a = repo.resolve_single(settings, "description(exact:'A')")

    new_repo = mutations.set_bookmark(workspace, repo, settings, a, "release")

    assert new_repo.resolve_single(settings, "@").id == wc.id


def test_undo_reverts_the_last_operation(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    repo = mutations.abandon(workspace, repo, settings, [a])
    assert repo.revset(settings, "description(exact:'A')") == []

    repo = mutations.undo(workspace, repo, settings)

    assert len(repo.revset(settings, "description(exact:'A')")) == 1


def test_redo_reapplies_the_undone_operation(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    repo = mutations.abandon(workspace, repo, settings, [a])
    repo = mutations.undo(workspace, repo, settings)
    assert len(repo.revset(settings, "description(exact:'A')")) == 1

    repo = mutations.redo(workspace, repo, settings)

    assert repo.revset(settings, "description(exact:'A')") == []
