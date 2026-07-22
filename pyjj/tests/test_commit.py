"""Tests for Commit properties and equality."""


def test_working_copy_commit_is_empty_and_discardable(repo, wc_commit):
    # A freshly-initialized working-copy commit has no changes yet and no
    # description, so it's both empty and discardable.
    assert wc_commit.is_empty(repo) is True
    assert wc_commit.is_discardable(repo) is True


def test_working_copy_commit_has_root_as_parent(repo, wc_commit):
    assert len(wc_commit.parent_ids) == 1
    root = repo.get_commit(wc_commit.parent_ids[0])
    assert root.description == ""


def test_working_copy_commit_flags(wc_commit):
    assert wc_commit.description == ""
    assert wc_commit.has_conflict is False
    assert wc_commit.is_signed is False


def test_working_copy_commit_author_and_committer_match_settings(settings, wc_commit):
    assert wc_commit.author.email == settings.user_email
    assert wc_commit.committer.email == settings.user_email


def test_commit_equality_and_hash(repo, wc_commit):
    same = repo.get_commit(wc_commit.id)
    other = repo.get_commit(wc_commit.parent_ids[0])
    assert wc_commit == same
    assert hash(wc_commit) == hash(same)
    assert wc_commit != other


def test_commit_repr_contains_change_and_commit_id(wc_commit):
    r = repr(wc_commit)
    assert wc_commit.change_id.reverse_hex() in r
    assert wc_commit.id.hex() in r
