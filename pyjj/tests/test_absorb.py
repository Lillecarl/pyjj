"""Tests for Transaction.absorb(): jj absorb equivalent.

Splits an undescribed (or described) commit's changes and moves each hunk
into the closest ancestor where the corresponding lines were last modified,
based on the same annotate/blame machinery Commit.annotate() uses.

Uses `pyjj.UserSettings()` (real config loaded) rather than the usual
`load_config=False` `settings` fixture, since the default `destinations`
("mutable()") is one of jj's bundled `revsets.toml` aliases -- same
constraint as test_revset.py's
test_immutable_and_mutable_via_bundled_revset_aliases.
"""

from pathlib import Path

import pyjj


def _new_child(repo, settings, ws, parent):
    """Advance to a fresh, undescribed child of `parent` so a subsequent
    snapshot() amends *that* commit, giving real ancestry to absorb across.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("new child")
    ws.check_out(repo, child)
    return repo


def _setup(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    path = Path(workspace_root, "a.txt")
    path.write_text("line1\nline2\nline3\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, base)
    builder.set_description("base commit")
    base = builder.write(repo)
    tx.set_wc_commit("default", base.id)
    tx.rebase_descendants()
    repo = tx.commit("describe base")
    ws.check_out(repo, base)

    return settings, ws, repo, base, path


def test_absorb_moves_the_hunk_into_the_commit_that_last_touched_the_line(tmp_path):
    settings, ws, repo, base, path = _setup(tmp_path)
    repo = _new_child(repo, settings, ws, base)

    path.write_text("line1\nLINE2-MODIFIED\nline3\n")
    repo, _ = ws.snapshot(settings)
    source_commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    stats = tx.absorb(settings, source_commit)
    tx.rebase_descendants()
    new_repo = tx.commit("absorb")

    # Fully absorbed into `base`, and the undescribed source is abandoned.
    assert stats.source is None
    assert len(stats.destinations) == 1
    absorbed = new_repo.get_commit(stats.destinations[0].id)
    assert absorbed.description == "base commit"
    assert absorbed.read_file("a.txt") == b"line1\nLINE2-MODIFIED\nline3\n"


def test_absorb_keeps_a_described_source_even_when_fully_absorbed(tmp_path):
    settings, ws, repo, base, path = _setup(tmp_path)
    repo = _new_child(repo, settings, ws, base)

    path.write_text("line1\nLINE2-MODIFIED\nline3\n")
    repo, _ = ws.snapshot(settings)
    source_commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, source_commit)
    builder.set_description("keep me even though everything absorbs away")
    source_commit = builder.write(repo)
    tx.set_wc_commit("default", source_commit.id)
    tx.rebase_descendants()
    repo = tx.commit("describe source")

    tx = repo.start_transaction(settings)
    stats = tx.absorb(settings, source_commit)
    tx.rebase_descendants()
    new_repo = tx.commit("absorb")

    assert stats.source is not None
    kept_source = new_repo.get_commit(stats.source.id)
    assert kept_source.description == "keep me even though everything absorbs away"
    # No diff of its own left -- everything moved to the destination.
    parent = new_repo.get_commit(kept_source.parent_ids[0])
    assert parent.diff(kept_source) == []


def test_absorb_respects_a_paths_filter(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    (workspace_root / "a.txt").write_text("a1\n")
    (workspace_root / "b.txt").write_text("b1\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, base)
    builder.set_description("base commit")
    base = builder.write(repo)
    tx.set_wc_commit("default", base.id)
    tx.rebase_descendants()
    repo = tx.commit("describe base")
    ws.check_out(repo, base)

    repo = _new_child(repo, settings, ws, base)
    (workspace_root / "a.txt").write_text("a1-changed\n")
    (workspace_root / "b.txt").write_text("b1-changed\n")
    repo, _ = ws.snapshot(settings)
    source_commit = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    stats = tx.absorb(settings, source_commit, paths=["a.txt"])
    tx.rebase_descendants()
    new_repo = tx.commit("absorb a.txt only")

    # a.txt's change absorbed away, b.txt's change stays in source.
    assert stats.source is not None
    remaining = new_repo.get_commit(stats.source.id)
    assert remaining.read_file("b.txt") == b"b1-changed\n"
    absorbed = new_repo.get_commit(stats.destinations[0].id)
    assert absorbed.read_file("a.txt") == b"a1-changed\n"
