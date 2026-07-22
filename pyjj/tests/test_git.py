"""Tests for Transaction.git_import_refs()/git_export_refs() against a
colocated Git repo.
"""

import subprocess
from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def colocated(tmp_path, settings):
    ws, repo = pyjj.Workspace.init_colocated_git(settings, str(tmp_path))
    return ws, repo


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_import_refs_with_nothing_to_import(colocated, settings):
    _ws, repo = colocated
    tx = repo.start_transaction(settings)
    stats = tx.git_import_refs()
    assert stats["changed_remote_bookmarks"] == 0
    assert stats["failed_ref_names"] == []


def test_import_refs_picks_up_git_side_commit(colocated, settings):
    ws, repo = colocated
    root = ws.workspace_root
    _git(root, "checkout", "-b", "feature")
    Path(root, "from_git.txt").write_text("made outside jj\n")
    _git(root, "add", "from_git.txt")
    _git(root, "commit", "-m", "git-side commit")

    tx = repo.start_transaction(settings)
    stats = tx.git_import_refs()
    assert stats["changed_remote_bookmarks"] == 1

    new_repo = tx.commit("import")
    bm = new_repo.get_bookmark("feature")
    assert bm is not None
    assert not bm.has_conflict

    imported_commit = new_repo.get_commit(bm.target_ids[0])
    assert imported_commit.description.strip() == "git-side commit"


def test_export_refs_with_nothing_to_export(colocated, settings):
    _ws, repo = colocated
    tx = repo.start_transaction(settings)
    stats = tx.git_export_refs()
    assert stats["failed_bookmarks"] == []
    assert stats["failed_tags"] == []


def test_export_refs_creates_git_ref_for_jj_bookmark(colocated, settings):
    ws, repo = colocated
    tx = repo.start_transaction(settings)

    view = repo.view()
    wc_commit_id = pyjj.CommitId(next(iter(view.values())))
    tx.set_bookmark("exported", wc_commit_id)
    stats = tx.git_export_refs()
    assert stats["failed_bookmarks"] == []
    tx.commit("export")

    result = subprocess.run(
        ["git", "show-ref", "--verify", "refs/heads/exported"],
        cwd=ws.workspace_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
