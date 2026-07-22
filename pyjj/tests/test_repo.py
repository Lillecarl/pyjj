"""Tests for ReadonlyRepo.view()/get_commit()."""

import pytest

import pyjj

ZERO_COMMIT_ID = "0" * 40


def test_view_maps_workspace_name_to_commit_hex(repo):
    view = repo.view()
    assert isinstance(view, dict)
    assert set(view.keys()) == {"default"}
    wc_hex = view["default"]
    assert isinstance(wc_hex, str)
    assert len(wc_hex) == 40  # SHA1 hex


def test_get_commit_roundtrips_the_working_copy_commit(repo, wc_commit):
    view = repo.view()
    again = repo.get_commit(pyjj.CommitId(view["default"]))
    assert again == wc_commit
    assert again.id == wc_commit.id


def test_get_commit_can_reach_the_root_commit(repo, wc_commit):
    root_id = wc_commit.parent_ids[0]
    root = repo.get_commit(root_id)
    assert root.id.hex() == ZERO_COMMIT_ID
    assert root.change_id.reverse_hex() == "z" * 32
    assert root.description == ""


def test_get_commit_unknown_id_raises_backend_error(repo):
    with pytest.raises(pyjj.BackendError):
        repo.get_commit(pyjj.CommitId("f" * 40))


def test_repo_repr_contains_operation_hex(repo):
    assert repr(repo).startswith("ReadonlyRepo(op=")
