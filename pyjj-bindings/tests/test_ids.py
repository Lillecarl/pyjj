"""Unit tests for the ID types (CommitId, ChangeId, TreeId, FileId)."""

import pytest

import pyjj_bindings as b

COMMIT_HEX = "a" * 40
CHANGE_HEX = "b" * 32
TREE_HEX = "c" * 40
FILE_HEX = "d" * 40


@pytest.mark.parametrize(
    "cls, hex_value",
    [
        (b.CommitId, COMMIT_HEX),
        (b.ChangeId, CHANGE_HEX),
        (b.TreeId, TREE_HEX),
        (b.FileId, FILE_HEX),
    ],
)
def test_hex_roundtrip(cls, hex_value):
    obj = cls(hex_value)
    assert obj.hex() == hex_value


@pytest.mark.parametrize("cls", [b.CommitId, b.ChangeId, b.TreeId, b.FileId])
def test_invalid_hex_raises_jjerror(cls):
    with pytest.raises(b.JjError) as exc_info:
        cls("not-hex-at-all")
    assert exc_info.value.message


def test_commit_id_short():
    cid = b.CommitId(COMMIT_HEX)
    assert cid.short(12) == COMMIT_HEX[:12]


def test_commit_id_str_and_repr():
    cid = b.CommitId(COMMIT_HEX)
    assert str(cid) == COMMIT_HEX
    assert repr(cid) == f"CommitId({COMMIT_HEX})"


def test_commit_id_equality_and_hash():
    a = b.CommitId(COMMIT_HEX)
    a2 = b.CommitId(COMMIT_HEX)
    other = b.CommitId("f" * 40)
    assert a == a2
    assert a != other
    assert hash(a) == hash(a2)
    assert {a, a2, other} == {a, other}


def test_commit_id_equality_with_non_commit_id_is_false():
    cid = b.CommitId(COMMIT_HEX)
    assert (cid == COMMIT_HEX) is False


def test_change_id_reverse_hex_and_str():
    # All-zero bytes reverse-hex-encode to all 'z'.
    change = b.ChangeId("0" * 32)
    assert change.reverse_hex() == "z" * 32
    assert str(change) == change.reverse_hex()
    assert repr(change) == f"ChangeId({change.reverse_hex()})"


def test_change_id_equality_and_hash():
    a = b.ChangeId(CHANGE_HEX)
    a2 = b.ChangeId(CHANGE_HEX)
    assert a == a2
    assert hash(a) == hash(a2)


def test_commit_id_length_is_not_validated_at_construction():
    # Construction only validates hex-ness, not that the length matches a
    # real backend hash length (that's only checked when the id is used,
    # e.g. ReadonlyRepo.get_commit).
    cid = b.CommitId("a" * 64)
    assert cid.hex() == "a" * 64


@pytest.mark.parametrize("cls", [b.TreeId, b.FileId])
def test_tree_and_file_id_are_unhashable(cls):
    # TreeId/FileId define __eq__ but not __hash__, so (like plain Python
    # objects with __eq__ only) they're unhashable.
    obj = cls(TREE_HEX)
    with pytest.raises(TypeError):
        hash(obj)


@pytest.mark.parametrize("cls", [b.TreeId, b.FileId])
def test_tree_and_file_id_str_falls_back_to_repr(cls):
    obj = cls(TREE_HEX)
    assert str(obj) == repr(obj)


def test_tree_id_equality():
    a = b.TreeId(TREE_HEX)
    a2 = b.TreeId(TREE_HEX)
    other = b.TreeId("e" * 40)
    assert a == a2
    assert a != other


def test_file_id_equality():
    a = b.FileId(FILE_HEX)
    a2 = b.FileId(FILE_HEX)
    other = b.FileId("e" * 40)
    assert a == a2
    assert a != other
