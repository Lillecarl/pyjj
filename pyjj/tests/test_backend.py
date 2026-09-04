"""Tests for ReadonlyRepo.backend_name -- `jj util backend name`.

The name identifies the storage format, and jj writes it to
`.jj/repo/store/type` when the repo is created.
"""

from pathlib import Path


def test_backend_name_is_the_stored_type(workspace, repo):
    stored = Path(workspace.repo_path, "store", "type").read_text().strip()
    assert repo.backend_name == stored


def test_backend_name_of_a_git_repo(repo):
    assert repo.backend_name == "git"


def test_backend_name_survives_a_transaction(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    new_repo = tx.commit("empty")
    assert new_repo.backend_name == repo.backend_name
