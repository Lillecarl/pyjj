"""Tests for ReadonlyRepo.revset()/resolve_single(): parsing and evaluation."""

import pytest

import pyjj


def test_at_symbol_resolves_to_wc_commit(repo, settings, wc_commit):
    commits = repo.revset(settings, "@")
    assert commits == [wc_commit]


def test_root_resolves_to_root_commit(repo, settings):
    commits = repo.revset(settings, "root()")
    assert len(commits) == 1
    assert commits[0].id == pyjj.CommitId("0" * 40)


def test_union_of_root_and_wc(repo, settings, wc_commit):
    commits = repo.revset(settings, "root() | @")
    assert {c.id for c in commits} == {pyjj.CommitId("0" * 40), wc_commit.id}


def test_ancestors_of_wc_includes_root(repo, settings, wc_commit):
    commits = repo.revset(settings, "ancestors(@)")
    assert {c.id for c in commits} == {pyjj.CommitId("0" * 40), wc_commit.id}


def test_none_resolves_to_empty(repo, settings):
    assert repo.revset(settings, "none()") == []


def test_invalid_syntax_raises_revset_parse_error(repo, settings):
    with pytest.raises(pyjj.RevsetParseError):
        repo.revset(settings, "@ &")


def test_resolve_single_returns_the_one_match(repo, settings, wc_commit):
    assert repo.resolve_single(settings, "@") == wc_commit


def test_resolve_single_raises_on_no_match(repo, settings):
    with pytest.raises(pyjj.RevsetEvalError):
        repo.resolve_single(settings, "none()")


def test_resolve_single_raises_on_multiple_matches(repo, settings, wc_commit):
    with pytest.raises(pyjj.RevsetEvalError):
        repo.resolve_single(settings, "root() | @")


def test_commit_id_prefix_resolves(repo, settings, wc_commit):
    full_hex = wc_commit.id.hex()
    commits = repo.revset(settings, full_hex[:8])
    assert commits == [wc_commit]


def test_immutable_and_mutable_via_bundled_revset_aliases(tmp_path):
    """pyjj has no bespoke "is this commit immutable" API -- jj's CLI-layer
    rewrite guard (`check_rewritable` in cli/src/cli_util.rs) is itself just
    policy built on the `immutable()`/`mutable()` revset aliases from jj's
    bundled `revsets.toml` (`'immutable()' = '::(immutable_heads() | root())'`).
    Those aliases are already usable today through the existing `revset()`
    binding, as long as `UserSettings(load_config=True)` (the default) is
    used, so no new Rust binding is needed for callers who want the same
    rewrite-safety semantics as the real `jj` CLI.
    """
    settings = pyjj.UserSettings()  # load_config=True (default) loads revsets.toml
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))
    wc = repo.get_commit(pyjj.CommitId(next(iter(repo.view().values()))))

    assert repo.revset(settings, "root() & immutable()") != []
    assert repo.revset(settings, f"{wc.id.hex()} & immutable()") == []
    assert repo.revset(settings, f"{wc.id.hex()} & mutable()") == [wc]


def test_parents_and_descendants_functions(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("child")
    child = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("add child")

    assert repo2.revset(settings, f"parents({child.id.hex()})") == [wc_commit]
    assert {c.id for c in repo2.revset(settings, f"descendants({wc_commit.id.hex()})")} == {
        wc_commit.id,
        child.id,
    }


def test_heads_function_returns_tip_commits(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("child")
    child = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("add child")

    heads = repo2.revset(settings, f"heads({wc_commit.id.hex()} | {child.id.hex()})")
    assert heads == [child]


def test_description_pattern_matches_commit_message(repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("fix: a specific bug")
    child = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("add child")

    assert repo2.revset(settings, 'description(glob:"fix:*")') == [child]
    assert repo2.revset(settings, 'description(glob:"nope*")') == []
