"""Tests for Workspace.clone_git() -- the `jj git clone` equivalent.

Uses a local bare Git repo as the "remote" so these run without network
access, same approach as test_git_remote.py.
"""

import os
import subprocess

import pytest

import pyjj


def _git(cwd, *args):
    # Neutralize machine git config that could hijack these seed commands:
    # a headless editor (e.g. for force-sign-annotated tags) panics without
    # a terminal, and signing needs keys this environment doesn't have.
    env = {**os.environ, "GIT_EDITOR": "true", "EDITOR": "true"}
    subprocess.run(
        [
            "git",
            "-c", "user.email=a@b.c",
            "-c", "user.name=A",
            "-c", "tag.gpgsign=false",
            "-c", "tag.forcesignannotated=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def bare_remote(tmp_path_factory):
    """A bare git repo with two branches ('main', 'other') and a tag
    ('v1.0' on main). 'main' is the default branch (HEAD).
    """
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

    _git(seed_dir, "checkout", "-b", "other")
    (seed_dir / "OTHER.md").write_text("other\n")
    _git(seed_dir, "add", "OTHER.md")
    _git(seed_dir, "commit", "-m", "other branch commit")
    _git(seed_dir, "push", str(remote_dir), "other")

    _git(seed_dir, "tag", "v1.0", "main")
    _git(seed_dir, "push", str(remote_dir), "v1.0")

    return remote_dir


def test_clone_git_fetches_everything_and_tracks_default_branch(bare_remote, settings, tmp_path):
    dest = tmp_path / "clone-dest"
    ws, repo = pyjj.Workspace.clone_git(settings, str(bare_remote), str(dest))

    assert repo.git_remotes() == ["origin"]
    assert {b.name for b in repo.bookmarks()} == {"main"}
    assert {t.name for t in repo.tags()} == {"v1.0"}

    # "other" was fetched (as a remote-tracking bookmark) even though it
    # isn't tracked locally -- tracking it now should work only if it was
    # actually fetched.
    tx = repo.start_transaction(settings)
    tx.git_track_remote_bookmark("origin", "other")
    repo2 = tx.commit("track other")
    assert repo2.get_bookmark("other") is not None


def test_clone_git_checks_out_default_branch_as_a_child_commit(bare_remote, settings, tmp_path):
    dest = tmp_path / "clone-dest"
    ws, repo = pyjj.Workspace.clone_git(settings, str(bare_remote), str(dest))

    assert (dest / "README.md").exists()
    assert not (dest / "OTHER.md").exists()

    wc = repo.resolve_single(settings, "@")
    main_bm = repo.get_bookmark("main")
    # The working copy is a *child* of main, not main itself -- so editing
    # files doesn't silently move the bookmark.
    assert wc.parent_ids == main_bm.target_ids
    assert wc.id != main_bm.target_ids[0]


def test_clone_git_no_colocate(bare_remote, settings, tmp_path):
    dest = tmp_path / "clone-dest"
    ws, repo = pyjj.Workspace.clone_git(settings, str(bare_remote), str(dest), colocate=False)
    assert not (dest / ".git").exists()
    assert (dest / "README.md").exists()


def test_clone_git_custom_remote_name(bare_remote, settings, tmp_path):
    dest = tmp_path / "clone-dest"
    ws, repo = pyjj.Workspace.clone_git(
        settings, str(bare_remote), str(dest), remote_name="upstream"
    )
    assert repo.git_remotes() == ["upstream"]


def test_clone_git_nonempty_destination_raises(bare_remote, settings, tmp_path):
    dest = tmp_path / "clone-dest"
    dest.mkdir()
    (dest / "existing.txt").write_text("already here\n")
    with pytest.raises(pyjj.JjError):
        pyjj.Workspace.clone_git(settings, str(bare_remote), str(dest))
