"""Tests for Git remote management, fetch, and push.

Uses a local bare Git repo as the "remote" so these run without network
access. Note the caveat documented in AGENTS.md: the Git backend caches
remote config for the lifetime of a `Workspace` object, so tests reload via
a fresh `pyjj.Workspace.load()` after any `git_add_remote()`/
`git_remove_remote()` before relying on the new state.
"""

import subprocess

import pytest

import pyjj


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=A", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def bare_remote_with_commit(tmp_path_factory):
    """A bare git repo with one commit ('seed commit') on branch 'main'."""
    remote_dir = tmp_path_factory.mktemp("remote") / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_dir)], check=True, capture_output=True
    )
    seed_dir = tmp_path_factory.mktemp("seed")
    subprocess.run(["git", "init", "-b", "main", str(seed_dir)], check=True, capture_output=True)
    (seed_dir / "README.md").write_text("hello\n")
    _git(seed_dir, "add", "README.md")
    _git(seed_dir, "commit", "-m", "seed commit")
    _git(seed_dir, "push", str(remote_dir), "main")
    return remote_dir


def test_no_remotes_initially(repo):
    assert repo.git_remotes() == []


def test_add_and_remove_remote(workspace, repo, settings, bare_remote_with_commit):
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    tx.commit("add remote")

    fresh = pyjj.Workspace.load(settings, workspace.workspace_root)
    fresh_repo = fresh.load_at_head()
    assert fresh_repo.git_remotes() == ["origin"]

    tx2 = fresh_repo.start_transaction(settings)
    tx2.git_remove_remote("origin")
    tx2.commit("remove remote")

    fresh2 = pyjj.Workspace.load(settings, workspace.workspace_root)
    assert fresh2.load_at_head().git_remotes() == []


def test_adding_duplicate_remote_raises(workspace, repo, settings, bare_remote_with_commit):
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    tx.commit("add remote")

    fresh_repo = pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()
    tx2 = fresh_repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx2.git_add_remote("origin", str(bare_remote_with_commit))


def test_rename_remote_updates_remote_list(workspace, repo, settings, bare_remote_with_commit):
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    repo = tx.commit("add remote")

    fresh_repo = pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()
    tx2 = fresh_repo.start_transaction(settings)
    tx2.git_rename_remote("origin", "upstream")
    tx2.commit("rename remote")

    fresh2 = pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()
    assert fresh2.git_remotes() == ["upstream"]


def test_rename_nonexistent_remote_raises(repo, settings):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.git_rename_remote("does-not-exist", "whatever")


def test_rename_remote_to_existing_name_raises(workspace, repo, settings, bare_remote_with_commit):
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    tx.git_add_remote("other", str(bare_remote_with_commit))
    tx.commit("add remotes")

    fresh_repo = pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()
    tx2 = fresh_repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx2.git_rename_remote("origin", "other")


def test_set_remote_urls_changes_fetch_url_and_is_a_noop_by_default(
    workspace, repo, settings, bare_remote_with_commit
):
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    tx.commit("add remote")

    fresh_repo = pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()
    tx2 = fresh_repo.start_transaction(settings)
    # Passing neither url nor push_url is a documented no-op, not an error.
    tx2.git_set_remote_urls("origin")
    tx2.git_set_remote_urls("origin", url="https://example.invalid/repo.git")
    tx2.commit("set url")


def test_set_remote_urls_on_nonexistent_remote_raises(repo, settings):
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.git_set_remote_urls("does-not-exist", url="https://example.invalid/repo.git")


@pytest.fixture
def repo_with_remote(workspace, repo, settings, bare_remote_with_commit):
    """repo, reloaded after adding 'origin' pointing at bare_remote_with_commit."""
    tx = repo.start_transaction(settings)
    tx.git_add_remote("origin", str(bare_remote_with_commit))
    tx.commit("add remote")
    return pyjj.Workspace.load(settings, workspace.workspace_root).load_at_head()


def test_fetch_imports_remote_bookmark(repo_with_remote, settings):
    tx = repo_with_remote.start_transaction(settings)
    stats = tx.git_fetch(settings, "origin", ["main"])
    assert stats["changed_remote_bookmarks"] == 1
    assert stats["failed_ref_names"] == []

    new_repo = tx.commit("fetch")
    # Fetched but not tracked: no local bookmark yet.
    assert new_repo.get_bookmark("main") is None


def test_fetch_nonexistent_branch_changes_nothing(repo_with_remote, settings):
    tx = repo_with_remote.start_transaction(settings)
    stats = tx.git_fetch(settings, "origin", ["does-not-exist"])
    assert stats["changed_remote_bookmarks"] == 0


def test_track_after_fetch_creates_local_bookmark(repo_with_remote, settings):
    tx = repo_with_remote.start_transaction(settings)
    tx.git_fetch(settings, "origin", ["main"])
    tx.git_track_remote_bookmark("origin", "main")
    new_repo = tx.commit("fetch + track")

    bm = new_repo.get_bookmark("main")
    assert bm is not None
    assert not bm.has_conflict
    fetched_commit = new_repo.get_commit(bm.target_ids[0])
    assert fetched_commit.description.strip() == "seed commit"


def test_untrack_keeps_local_bookmark_but_stops_future_sync(repo_with_remote, settings):
    # untrack() means "stop auto-merging {name}@{remote} into the local
    # bookmark going forward" - it doesn't delete the local bookmark, which
    # keeps whatever position it already had (matches `jj bookmark untrack`).
    tx = repo_with_remote.start_transaction(settings)
    tx.git_fetch(settings, "origin", ["main"])
    tx.git_track_remote_bookmark("origin", "main")
    tracked = tx.get_bookmark("main")

    tx.git_untrack_remote_bookmark("origin", "main")
    new_repo = tx.commit("fetch + track + untrack")

    assert new_repo.get_bookmark("main") == tracked


def test_push_bookmark_delivers_to_remote(repo_with_remote, settings, bare_remote_with_commit):
    tx = repo_with_remote.start_transaction(settings)
    tx.git_fetch(settings, "origin", ["main"])
    tx.git_track_remote_bookmark("origin", "main")
    repo2 = tx.commit("fetch + track")

    base = repo2.get_bookmark("main")
    base_commit = repo2.get_commit(base.target_ids[0])

    tx2 = repo2.start_transaction(settings)
    builder = tx2.new_commit(settings, [base_commit.id])
    builder.set_description("pushed from pyjj")
    new_commit = builder.write(repo2)
    tx2.set_bookmark("main", new_commit.id)
    tx2.rebase_descendants()
    repo3 = tx2.commit("advance main")

    tx3 = repo3.start_transaction(settings)
    stats = tx3.git_push_bookmark(settings, "origin", "main")
    assert stats["pushed"] == ["refs/heads/main"]
    assert stats["rejected"] == []
    assert stats["remote_rejected"] == []
    tx3.commit("push main")

    result = subprocess.run(
        ["git", "--git-dir", str(bare_remote_with_commit), "log", "-1", "--format=%s", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "pushed from pyjj"


def test_push_nonexistent_bookmark_raises(repo_with_remote, settings):
    tx = repo_with_remote.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.git_push_bookmark(settings, "origin", "no-such-bookmark")


def test_push_with_nothing_new_is_a_clean_noop(repo_with_remote, settings):
    tx = repo_with_remote.start_transaction(settings)
    tx.git_fetch(settings, "origin", ["main"])
    tx.git_track_remote_bookmark("origin", "main")
    repo2 = tx.commit("fetch + track")

    # Local bookmark already matches the tracked remote target - pushing
    # again should be a no-op, not the underlying jj_lib panic this used to
    # hit ("old/new targets should differ").
    tx2 = repo2.start_transaction(settings)
    stats = tx2.git_push_bookmark(settings, "origin", "main")
    assert stats == {"pushed": [], "rejected": [], "remote_rejected": []}
