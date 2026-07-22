"""Tests for Transaction.split_selected()/split_remainder(): jj split equivalent."""

from pathlib import Path

import pytest

import pyjj


@pytest.fixture
def commit_with_three_files(workspace, repo, settings):
    """A single commit touching a.txt, b.txt, c.txt, built from a real
    snapshot so the tree reflects genuine file content."""
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("a\n")
    (root / "b.txt").write_text("b\n")
    (root / "c.txt").write_text("c\n")
    repo, _ = workspace.snapshot(settings)
    return repo, repo.resolve_single(settings, "@")


def test_split_selected_has_only_matched_paths(commit_with_three_files, settings):
    repo, target = commit_with_three_files
    tx = repo.start_transaction(settings)
    builder = tx.split_selected(target, ["b.txt", "c.txt"])
    builder.set_description("part 1: b+c")
    first = builder.write(repo)

    assert not first.file_exists("a.txt")
    assert first.file_exists("b.txt")
    assert first.file_exists("c.txt")
    assert first.parent_ids == target.parent_ids


def test_split_selected_keeps_original_change_id(commit_with_three_files, settings):
    repo, target = commit_with_three_files
    tx = repo.start_transaction(settings)
    builder = tx.split_selected(target, ["a.txt"])
    builder.set_description("part 1: a")
    first = builder.write(repo)

    assert first.change_id == target.change_id
    assert first.id != target.id


def test_split_remainder_is_child_of_first_with_full_content(commit_with_three_files, settings):
    repo, target = commit_with_three_files
    tx = repo.start_transaction(settings)

    first_builder = tx.split_selected(target, ["b.txt", "c.txt"])
    first_builder.set_description("part 1: b+c")
    first = first_builder.write(repo)

    second_builder = tx.split_remainder(target, first)
    second_builder.set_description("part 2: a")
    second = second_builder.write(repo)

    assert second.parent_ids == [first.id]
    assert second.file_exists("a.txt")
    assert second.file_exists("b.txt")
    assert second.file_exists("c.txt")
    # second's own diff against first is just the remaining path
    assert {e.path for e in first.diff(second)} == {"a.txt"}


def test_split_remainder_gets_a_fresh_change_id(commit_with_three_files, settings):
    repo, target = commit_with_three_files
    tx = repo.start_transaction(settings)
    first = tx.split_selected(target, ["b.txt"]).write(repo)
    second = tx.split_remainder(target, first).write(repo)

    assert second.change_id != first.change_id
    assert second.change_id != target.change_id


def test_full_split_workflow_updates_wc_and_rebases(commit_with_three_files, settings):
    repo, target = commit_with_three_files
    tx = repo.start_transaction(settings)

    first_builder = tx.split_selected(target, ["b.txt", "c.txt"])
    first_builder.set_description("part 1: b+c")
    first = first_builder.write(repo)

    second_builder = tx.split_remainder(target, first)
    second_builder.set_description("part 2: a")
    second = second_builder.write(repo)

    tx.set_wc_commit("default", second.id)
    rebased_count = tx.rebase_descendants()
    new_repo = tx.commit("split target")

    assert isinstance(rebased_count, int)
    assert new_repo.resolve_single(settings, "@") == second
    assert new_repo.get_commit(first.id) == first
