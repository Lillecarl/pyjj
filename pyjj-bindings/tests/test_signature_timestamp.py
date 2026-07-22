"""Unit tests for Timestamp and Signature."""

import pyjj_bindings as b


def test_timestamp_getters():
    ts = b.Timestamp(1_700_000_000_000, -120)
    assert ts.millis_since_epoch == 1_700_000_000_000
    assert ts.tz_offset_minutes == -120


def test_timestamp_repr():
    ts = b.Timestamp(1000, 0)
    assert repr(ts) == "Timestamp(1000, 0min)"


def test_signature_getters():
    ts = b.Timestamp(0, 0)
    sig = b.Signature("Ada Lovelace", "ada@example.com", ts)
    assert sig.name == "Ada Lovelace"
    assert sig.email == "ada@example.com"
    assert sig.timestamp.millis_since_epoch == 0


def test_signature_repr():
    ts = b.Timestamp(0, 0)
    sig = b.Signature("Ada", "ada@example.com", ts)
    assert repr(sig) == "Signature(Ada <ada@example.com>)"
