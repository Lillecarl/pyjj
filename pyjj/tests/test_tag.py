"""Tests for local tags: read via ReadonlyRepo, mutate via Transaction.

Mirrors test_bookmark.py -- tags share the same RefTarget/RefName
machinery as bookmarks, but live in a separate namespace.
"""

import pyjj


def test_no_tags_initially(repo):
    assert repo.tags() == []
    assert repo.get_tag("v1.0") is None


def test_set_tag_visible_within_transaction(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_tag("v1.0", wc_commit.id)

    tag = tx.get_tag("v1.0")
    assert tag.name == "v1.0"
    assert tag.target_ids == [wc_commit.id]
    assert not tag.has_conflict
    assert tx.tags() == [tag]


def test_set_tag_visible_after_commit(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_tag("v1.0", wc_commit.id)
    new_repo = tx.commit("add tag")

    tag = new_repo.get_tag("v1.0")
    assert tag.name == "v1.0"
    assert tag.target_ids == [wc_commit.id]
    assert new_repo.tags() == [tag]


def test_delete_tag(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_tag("v1.0", wc_commit.id)
    tx.delete_tag("v1.0")

    assert tx.get_tag("v1.0") is None
    assert tx.tags() == []


def test_tag_repr(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_tag("v1.0", wc_commit.id)
    tag = tx.get_tag("v1.0")
    assert repr(tag) == "Tag(v1.0, conflict=False)"


def test_tags_and_bookmarks_are_separate_namespaces(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    tx.set_tag("shared-name", wc_commit.id)
    new_repo = tx.commit("add tag named 'shared-name'")

    assert new_repo.get_tag("shared-name") is not None
    assert new_repo.get_bookmark("shared-name") is None
