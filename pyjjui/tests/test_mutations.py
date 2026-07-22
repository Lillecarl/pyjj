"""Tests for mutations.py's sync (workspace, repo, settings, ...) -> ReadonlyRepo functions."""

from pyjjui import mutations


def test_new_child_creates_and_checks_out_a_child(workspace, settings, seeded_repo):
    repo = seeded_repo
    parent = repo.resolve_single(settings, "@")

    new_repo = mutations.new_child(workspace, repo, settings, parent)

    wc = new_repo.resolve_single(settings, "@")
    assert wc.id != parent.id
    assert wc.parent_ids == [parent.id]


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

    new_repo = mutations.abandon(workspace, repo, settings, a)

    assert new_repo.revset(settings, "description(exact:'A')") == []


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
    repo = mutations.abandon(workspace, repo, settings, a)
    assert repo.revset(settings, "description(exact:'A')") == []

    repo = mutations.undo(workspace, repo, settings)

    assert len(repo.revset(settings, "description(exact:'A')")) == 1


def test_redo_reapplies_the_undone_operation(workspace, settings, seeded_repo):
    repo = seeded_repo
    a = repo.resolve_single(settings, "description(exact:'A')")
    repo = mutations.abandon(workspace, repo, settings, a)
    repo = mutations.undo(workspace, repo, settings)
    assert len(repo.revset(settings, "description(exact:'A')")) == 1

    repo = mutations.redo(workspace, repo, settings)

    assert repo.revset(settings, "description(exact:'A')") == []
