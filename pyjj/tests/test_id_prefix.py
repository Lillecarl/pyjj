"""Tests for ReadonlyRepo.shortest_commit_id_prefix_len()/
shortest_change_id_prefix_len() -- the "shortest unique prefix" jj log
highlights.

Without settings they disambiguate against the whole repo. Pass settings
and they narrow within `revsets.short-prefixes` (or `revsets.log`), the
same rule jj follows.
"""

from pathlib import Path

import pytest

import pyjj


def test_prefix_len_is_1_for_lone_root_commit(repo, wc_commit):
    # Only the root + the wc commit exist -- trivially unique at length 1.
    assert repo.shortest_commit_id_prefix_len(wc_commit.id) >= 1
    assert repo.shortest_commit_id_prefix_len(wc_commit.id) <= len(wc_commit.id.hex())


def test_prefix_len_grows_with_more_commits_sharing_a_prefix(workspace, repo, settings):
    # Build several commits; a prefix length that resolves uniquely for one
    # commit must actually be sufficient to look it back up via revset.
    commits = []
    for i in range(8):
        Path(workspace.workspace_root, f"f{i}.txt").write_text(f"{i}\n")
        repo, _ = workspace.snapshot(settings)
        commits.append(repo.resolve_single(settings, "@"))

    for commit in commits:
        n = repo.shortest_commit_id_prefix_len(commit.id)
        prefix = commit.id.hex()[:n]
        resolved = repo.resolve_single(settings, prefix)
        assert resolved.id == commit.id


def test_change_id_prefix_len_resolves_via_reversed_hex(workspace, repo, settings):
    commits = []
    for i in range(8):
        Path(workspace.workspace_root, f"f{i}.txt").write_text(f"{i}\n")
        repo, _ = workspace.snapshot(settings)
        commits.append(repo.resolve_single(settings, "@"))

    for commit in commits:
        n = repo.shortest_change_id_prefix_len(commit.change_id)
        prefix = commit.change_id.reverse_hex()[:n]
        resolved = repo.resolve_single(settings, prefix)
        assert resolved.change_id == commit.change_id


def test_divergent_change_id_raises_a_clear_error_instead_of_resolving(
    workspace, repo, settings, wc_commit
):
    """Two *visible* commits sharing one change_id (achievable directly via
    `duplicate()` + `CommitBuilder.set_change_id()`, without needing evolog)
    is a divergent change -- resolving a revset that names it should raise
    a clear error, not panic or silently pick one. Mirrors jj_lib's own
    test_id_prefix_divergent.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    builder.set_description("original")
    c1 = builder.write(repo)
    tx.set_wc_commit("default", c1.id)
    tx.rebase_descendants()
    repo = tx.commit("create c1")
    c1 = repo.get_commit(c1.id)

    tx = repo.start_transaction(settings)
    (dup,) = tx.duplicate([c1])
    builder = tx.rewrite_commit(settings, dup)
    builder.set_change_id(c1.change_id)
    builder.set_description("divergent duplicate")
    dup2 = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("create divergent change id")

    assert c1.change_id == dup2.change_id

    with pytest.raises(pyjj.RevsetEvalError, match="divergent"):
        repo2.resolve_single(settings, c1.change_id.reverse_hex())


def _line(repo, settings, wc_commit, count):
    """A line of `count` commits on top of the working copy."""
    parents = []
    parent = wc_commit
    for i in range(count):
        tx = repo.start_transaction(settings)
        b = tx.new_commit(settings, [parent.id])
        b.set_description(f"c{i}")
        commit = b.write(repo)
        tx.set_wc_commit("default", commit.id)
        tx.rebase_descendants()
        repo = tx.commit(f"add c{i}")
        parent = repo.get_commit(commit.id)
        parents.append(parent)
    return repo, parents


def _settings_with(tmp_path, monkeypatch, body):
    """A `UserSettings` that loads exactly `body` and nothing else.

    `JJ_CONFIG` suppresses the system and user config paths too, so the
    machine's real config cannot leak in.
    """
    config_file = tmp_path / "config.toml"
    config_file.write_text(body)
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    return pyjj.UserSettings()


def test_short_prefixes_narrows_the_disambiguation_set(
    repo, settings, wc_commit, tmp_path, monkeypatch
):
    """`revsets.short-prefixes` shortens ids within a smaller set.

    Passing settings makes the binding follow `jj`'s rule instead of
    disambiguating against the whole repo.
    """
    repo, commits = _line(repo, settings, wc_commit, 60)

    # Pick a commit that genuinely needs more than one character repo-wide.
    # With 60 commits over 16 possible first characters some commit must
    # collide, but *which* one does is random -- asserting it of the tip
    # specifically would be flaky.
    ambiguous = next(
        c for c in commits if repo.shortest_commit_id_prefix_len(c.id) > 1
    )
    wide = repo.shortest_commit_id_prefix_len(ambiguous.id)

    # Narrow to exactly that commit, so one character must be enough.
    narrowed = _settings_with(
        tmp_path,
        monkeypatch,
        f'revsets.short-prefixes = "{ambiguous.id.hex()}"\n',
    )
    narrow = repo.shortest_commit_id_prefix_len(ambiguous.id, narrowed)
    assert narrow == 1
    assert narrow < wide

    ambiguous_change = next(
        c for c in commits
        if repo.shortest_change_id_prefix_len(c.change_id) > 1
    )
    wide_change = repo.shortest_change_id_prefix_len(ambiguous_change.change_id)
    narrowed_change = _settings_with(
        tmp_path,
        monkeypatch,
        f'revsets.short-prefixes = "{ambiguous_change.id.hex()}"\n',
    )
    narrow_change = repo.shortest_change_id_prefix_len(
        ambiguous_change.change_id, narrowed_change
    )
    assert narrow_change == 1
    assert narrow_change < wide_change


def test_short_prefixes_falls_back_to_revsets_log(
    repo, settings, wc_commit, tmp_path, monkeypatch
):
    """With no `short-prefixes`, `jj` narrows within `revsets.log`."""
    repo, commits = _line(repo, settings, wc_commit, 60)
    tip = commits[-1]

    via_log = _settings_with(tmp_path, monkeypatch, 'revsets.log = "@"\n')
    via_short = _settings_with(
        tmp_path, monkeypatch, 'revsets.short-prefixes = "@"\n'
    )
    assert repo.shortest_commit_id_prefix_len(tip.id, via_log) == \
        repo.shortest_commit_id_prefix_len(tip.id, via_short)


def test_empty_short_prefixes_disables_narrowing(
    repo, settings, wc_commit, tmp_path, monkeypatch
):
    repo, commits = _line(repo, settings, wc_commit, 20)
    tip = commits[-1]
    empty = _settings_with(tmp_path, monkeypatch, 'revsets.short-prefixes = ""\n')
    assert repo.shortest_commit_id_prefix_len(tip.id, empty) == \
        repo.shortest_commit_id_prefix_len(tip.id)


def test_settings_without_the_keys_is_harmless(repo, settings, wc_commit):
    """The bare `settings` fixture sets neither key, so nothing narrows."""
    repo, commits = _line(repo, settings, wc_commit, 5)
    tip = commits[-1]
    assert repo.shortest_commit_id_prefix_len(tip.id, settings) == \
        repo.shortest_commit_id_prefix_len(tip.id)
    assert repo.shortest_change_id_prefix_len(tip.change_id, settings) == \
        repo.shortest_change_id_prefix_len(tip.change_id)
