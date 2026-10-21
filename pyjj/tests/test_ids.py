"""Value semantics of the id and error types."""

import pickle

import pytest

import pyjj


def test_ids_are_hashable_and_ordered():
    a, b = pyjj.TreeId("00" * 20), pyjj.TreeId("01" * 20)
    assert len({a, pyjj.TreeId("00" * 20), b}) == 2
    assert sorted([b, a]) == [a, b]
    assert hash(pyjj.FileId("ab" * 20)) == hash(pyjj.FileId("ab" * 20))


def test_change_id_round_trips_through_str(wc_commit):
    change_id = wc_commit.change_id
    assert pyjj.ChangeId(str(change_id)) == change_id
    assert pyjj.ChangeId(change_id.hex()) == change_id


def test_short_longer_than_the_id_returns_all_of_it(wc_commit):
    assert wc_commit.id.short(100) == wc_commit.id.hex()


def test_errors_pickle():
    error = pickle.loads(pickle.dumps(pyjj.TransactionError("boom")))
    assert isinstance(error, pyjj.TransactionError)
    assert error.message == "boom"


def test_bad_config_raises_config_error(settings):
    with pytest.raises(pyjj.ConfigError):
        settings.with_command_args([("config", "no-equals-sign")])


def test_repo_index_error_does_not_shadow_the_builtin():
    assert not hasattr(pyjj, "IndexError")
    assert issubclass(pyjj.RepoIndexError, pyjj.JjError)
