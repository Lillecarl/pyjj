"""Tests for Transaction.check_rewritable -- jj's rewrite guard.

The immutable set is whatever `immutable()` resolves to, which is jj's
bundled `::(immutable_heads() | root())`. Those aliases live in jj's own
`revsets.toml`, so these tests use `UserSettings()` with config loading
on, unlike most of the suite. Same reason `test_revset.py` does.

A tag is the cheapest way to make a *non-root* commit immutable:
`builtin_immutable_heads()` is `trunk() | tags() | untracked_remote_
bookmarks()`, and a local repository has no remote for the other two.
"""

import pytest

import pyjj


@pytest.fixture
def live(tmp_path):
    """A repo whose settings see jj's bundled revset aliases."""
    settings = pyjj.UserSettings()
    root_dir = tmp_path / "repo"
    root_dir.mkdir()
    _ws, repo = pyjj.Workspace.init_internal_git(settings, str(root_dir))
    wc = repo.get_commit(pyjj.CommitId(next(iter(repo.view().values()))))
    return settings, repo, wc


def test_a_mutable_commit_passes(live):
    settings, repo, wc = live
    tx = repo.start_transaction(settings)
    tx.check_rewritable(settings, [wc.id])


def test_an_empty_set_passes(live):
    settings, repo, _wc = live
    tx = repo.start_transaction(settings)
    tx.check_rewritable(settings, [])


def test_the_root_commit_is_immutable(live):
    settings, repo, _wc = live
    root = repo.resolve_single(settings, "root()")
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="The root commit .* is immutable"):
        tx.check_rewritable(settings, [root.id])


def test_a_tagged_commit_is_immutable(live):
    """`tags()` is part of `builtin_immutable_heads()`, so tagging a
    commit protects it and everything it descends from."""
    settings, repo, wc = live
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc.id])
    builder.set_description("released")
    released = builder.write(repo)
    tx.set_tag("v1", released.id)
    tx.rebase_descendants()
    repo = tx.commit("tag it")

    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match=f"Commit {released.id.hex()[:12]} is immutable"):
        tx.check_rewritable(settings, [released.id])


def test_a_descendant_of_a_tag_stays_mutable(live):
    """Only the tagged commit and its ancestors are protected."""
    settings, repo, wc = live
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc.id])
    builder.set_description("released")
    released = builder.write(repo)
    builder = tx.new_commit(settings, [released.id])
    builder.set_description("after")
    after = builder.write(repo)
    tx.set_tag("v1", released.id)
    tx.rebase_descendants()
    repo = tx.commit("tag it")

    tx = repo.start_transaction(settings)
    tx.check_rewritable(settings, [after.id])


def test_a_mixed_set_reports_the_immutable_one(live):
    settings, repo, wc = live
    root = repo.resolve_single(settings, "root()")
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="immutable"):
        tx.check_rewritable(settings, [wc.id, root.id])


def test_without_bundled_config_it_says_so(tmp_path):
    """`immutable()` is jj's own alias, so the check needs the config
    layer that defines it. Opting out must not surface as a bare
    "function doesn't exist" parse error."""
    settings = pyjj.UserSettings(load_config=False)
    root_dir = tmp_path / "repo"
    root_dir.mkdir()
    _ws, repo = pyjj.Workspace.init_internal_git(settings, str(root_dir))
    wc = repo.get_commit(pyjj.CommitId(next(iter(repo.view().values()))))
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="load_config=False"):
        tx.check_rewritable(settings, [wc.id])


def test_fix_enumerate_does_not_check_by_default(tmp_path):
    """The check is policy, so the primitives keep it off. `fix_enumerate`
    must still run on settings that never loaded jj's config."""
    settings = pyjj.UserSettings(load_config=False)
    root_dir = tmp_path / "repo"
    root_dir.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(root_dir))
    (root_dir / "a.txt").write_bytes(b"a\n")
    repo, _ = ws.snapshot(settings)
    tx = repo.start_transaction(settings)
    assert [f.path for f in tx.fix_enumerate(settings, revset="@")] == ["a.txt"]


def test_fix_enumerate_checks_when_asked(tmp_path):
    """`check_immutable=True` is what pyjj-cli passes, and it needs the
    alias the same way `check_rewritable` does."""
    settings = pyjj.UserSettings(load_config=False)
    root_dir = tmp_path / "repo"
    root_dir.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(root_dir))
    (root_dir / "a.txt").write_bytes(b"a\n")
    repo, _ = ws.snapshot(settings)
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError, match="load_config=False"):
        tx.fix_enumerate(settings, revset="@", check_immutable=True)
