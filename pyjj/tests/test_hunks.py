"""Tests for pyjj.diff_hunks() and hunk-level squash/split."""

from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def base_and_changed(workspace, repo, settings):
    """base: a.txt with 4 lines. changed: line1 and line3 edited, line5 added
    -- a child commit of base, built from real snapshots.
    """
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("line1\nline2\nline3\nline4\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [base.id])
    builder.set_description("wc seed")
    seed = builder.write(repo)
    tx.set_wc_commit("default", seed.id)
    tx.rebase_descendants()
    repo = tx.commit("advance")
    workspace.check_out(repo, seed)

    (root / "a.txt").write_text("LINE1\nline2\nLINE3\nline4\nline5\n")
    repo, _ = workspace.snapshot(settings)
    changed = repo.resolve_single(settings, "@")
    return repo, base, changed


def test_diff_hunks_finds_each_independent_change():
    before = b"line1\nline2\nline3\nline4\n"
    after = b"LINE1\nline2\nLINE3\nline4\nline5\n"
    hunks = pyjj.diff_hunks(before, after)

    assert [h.index for h in hunks] == [0, 1, 2]
    assert (hunks[0].before, hunks[0].after) == (b"line1\n", b"LINE1\n")
    assert (hunks[1].before, hunks[1].after) == (b"line3\n", b"LINE3\n")
    assert (hunks[2].before, hunks[2].after) == (b"", b"line5\n")


def test_diff_hunks_no_changes_is_empty():
    assert pyjj.diff_hunks(b"same\n", b"same\n") == []


def test_split_selected_by_single_hunk(base_and_changed, settings):
    repo, base, changed = base_and_changed
    tx = repo.start_transaction(settings)

    first_builder = tx.split_selected(changed, hunks={"a.txt": [0]})
    first_builder.set_description("only line1 change")
    first = first_builder.write(repo)

    assert first.read_file("a.txt") == b"LINE1\nline2\nline3\nline4\n"
    assert first.change_id == changed.change_id
    assert first.parent_ids == changed.parent_ids


def test_split_remainder_after_hunk_split_has_everything_else(base_and_changed, settings):
    repo, base, changed = base_and_changed
    tx = repo.start_transaction(settings)

    first = tx.split_selected(changed, hunks={"a.txt": [0]})
    first.set_description("only line1 change")
    first_commit = first.write(repo)

    second = tx.split_remainder(changed, first_commit)
    second.set_description("everything else")
    second_commit = second.write(repo)

    assert second_commit.parent_ids == [first_commit.id]
    assert second_commit.change_id != changed.change_id
    assert second_commit.read_file("a.txt") == b"LINE1\nline2\nLINE3\nline4\nline5\n"


def test_split_selected_multiple_hunks_from_same_file(base_and_changed, settings):
    repo, base, changed = base_and_changed
    tx = repo.start_transaction(settings)

    first = tx.split_selected(changed, hunks={"a.txt": [0, 2]})
    first.set_description("line1 change + line5 addition")
    first_commit = first.write(repo)

    assert first_commit.read_file("a.txt") == b"LINE1\nline2\nline3\nline4\nline5\n"


def test_squash_with_single_hunk_moves_only_that_change(base_and_changed, settings):
    repo, base, changed = base_and_changed
    tx = repo.start_transaction(settings)

    builder = tx.squash(changed, base, hunks={"a.txt": [1]}, keep_emptied=True)
    assert builder is not None
    builder.set_description("base + line3 change only")
    new_base = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("squash single hunk")

    assert new_base.read_file("a.txt") == b"line1\nline2\nLINE3\nline4\n"


def test_squash_combining_paths_and_hunks(base_and_changed, settings):
    """Whole-file `paths` and per-file `hunks` selections can be combined in
    one call: `paths` takes whole files, `hunks` takes specific lines from
    others.
    """
    repo, base, changed = base_and_changed

    tx = repo.start_transaction(settings)
    builder = tx.squash(changed, base, paths=None, hunks={"a.txt": [0, 1]}, keep_emptied=True)
    assert builder is not None
    builder.set_description("base + line1 and line3 changes")
    new_base = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("squash two hunks")

    assert new_base.read_file("a.txt") == b"LINE1\nline2\nLINE3\nline4\n"
