"""Tests for CommitBuilder: chaining, consumption, sign behavior."""

import pytest

import pyjj


def _builder(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    return tx, tx.rewrite_commit(settings, wc_commit)


def test_setters_are_chainable_and_return_self(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    result = builder.set_description("chained")
    assert result is builder


def test_set_author_and_committer(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    ts = pyjj.Timestamp(0, 0)
    sig = pyjj.Signature("Someone Else", "someone@example.com", ts)
    builder.set_author(sig).set_committer(sig)
    written = builder.write(repo)
    assert written.author.email == "someone@example.com"
    assert written.committer.email == "someone@example.com"


def test_timestamp_equality_and_hash():
    a = pyjj.Timestamp(1000, 60)
    b = pyjj.Timestamp(1000, 60)
    c = pyjj.Timestamp(2000, 60)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_signature_equality_and_hash():
    ts = pyjj.Timestamp(1000, 60)
    a = pyjj.Signature("Same Person", "same@example.com", ts)
    b = pyjj.Signature("Same Person", "same@example.com", ts)
    c = pyjj.Signature("Different Person", "same@example.com", ts)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_set_change_id(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    new_change_id = pyjj.ChangeId("1" * 32)
    builder.set_change_id(new_change_id)
    written = builder.write(repo)
    assert written.change_id == new_change_id


@pytest.mark.parametrize("behavior", ["drop", "keep", "own", "force"])
def test_set_sign_behavior_accepts_known_values(repo, settings, wc_commit, behavior):
    _tx, builder = _builder(repo, settings, wc_commit)
    result = builder.set_sign_behavior(behavior)
    assert result is builder


def test_set_sign_behavior_rejects_unknown_value(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    with pytest.raises(pyjj.JjError):
        builder.set_sign_behavior("not-a-real-behavior")


def test_write_twice_raises_transaction_error_not_a_panic(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    builder.set_description("first write")
    builder.write(repo)

    with pytest.raises(pyjj.TransactionError):
        builder.write(repo)


def test_setter_after_write_raises_transaction_error_not_a_panic(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    builder.write(repo)

    with pytest.raises(pyjj.TransactionError):
        builder.set_description("too late")


def test_abandon_consumes_builder(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    builder.abandon()
    with pytest.raises(pyjj.TransactionError):
        builder.write(repo)


def test_commit_builder_repr_reflects_consumed_state(repo, settings, wc_commit):
    _tx, builder = _builder(repo, settings, wc_commit)
    assert "CommitBuilder(" in repr(builder)
    assert repr(builder) != "CommitBuilder(consumed)"
    builder.write(repo)
    assert repr(builder) == "CommitBuilder(consumed)"
