"""Tests for Commit.materialize_conflict() and Transaction.resolve_conflict()."""

from pathlib import Path

import pytest

import pyjj


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


@pytest.fixture
def conflicted_commit(workspace, repo, settings):
    """A merge commit whose a.txt conflicts: base has 'line1\\nline2\\nline3\\n',
    side1 changes line2 to 'SIDE1', side2 (a sibling, also off base) changes
    line2 to 'SIDE2'.
    """
    _write(workspace, "a.txt", "line1\nline2\nline3\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    seed = tx.new_commit(settings, [base.id])
    seed.set_description("side1 seed")
    side1_seed = seed.write(repo)
    tx.set_wc_commit("default", side1_seed.id)
    tx.rebase_descendants()
    repo = tx.commit("advance to side1")
    workspace.check_out(repo, side1_seed)
    _write(workspace, "a.txt", "line1\nSIDE1\nline3\n")
    repo, _ = workspace.snapshot(settings)
    side1 = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    seed = tx.new_commit(settings, [base.id])
    seed.set_description("side2 seed")
    side2_seed = seed.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("advance to side2 seed")
    workspace.check_out(repo, side2_seed)
    _write(workspace, "a.txt", "line1\nSIDE2\nline3\n")
    repo, _ = workspace.snapshot(settings)
    side2 = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    merge_builder = tx.new_commit(settings, [side1.id, side2.id])
    merge_builder.set_description("merge side1+side2")
    merge_commit = merge_builder.write(repo)
    tx.set_wc_commit("default", merge_commit.id)
    tx.rebase_descendants()
    repo2 = tx.commit("create merge conflict")

    return repo2, repo2.resolve_single(settings, "@")


def test_new_commit_merges_multiple_parent_trees(conflicted_commit):
    """Regression check for the new_commit fix this feature required: a
    multi-parent new_commit() must actually merge the parents' trees (and
    conflict where they differ), not silently take just the first parent's
    tree.
    """
    repo, merged = conflicted_commit
    assert merged.has_conflict
    assert len(merged.parent_ids) == 2


def test_materialize_conflict(conflicted_commit, settings):
    _repo, merged = conflicted_commit
    text = merged.materialize_conflict(settings, "a.txt")
    assert b"<<<<<<<" in text
    assert b">>>>>>>" in text
    assert b"SIDE1" in text
    assert b"SIDE2" in text
    assert text.startswith(b"line1\n")
    assert text.endswith(b"line3\n")


def test_materialize_conflict_on_non_conflicted_path_raises(conflicted_commit, settings):
    _repo, merged = conflicted_commit
    with pytest.raises(pyjj.JjError):
        merged.materialize_conflict(settings, "no-such-file.txt")


def test_resolve_conflict_fully(conflicted_commit, settings):
    repo, merged = conflicted_commit
    tx = repo.start_transaction(settings)
    resolved_content = b"line1\nSIDE1-AND-SIDE2\nline3\n"
    builder = tx.resolve_conflict(merged, "a.txt", resolved_content)
    builder.set_description("resolve a.txt")
    resolved = builder.write(repo)
    tx.set_wc_commit("default", resolved.id)
    tx.rebase_descendants()
    repo2 = tx.commit("resolve conflict")

    assert not resolved.has_conflict
    assert resolved.read_file("a.txt") == resolved_content
    assert repo2.resolve_single(settings, "@") == resolved


def test_resolve_conflict_unchanged_text_stays_conflicted(conflicted_commit, settings):
    repo, merged = conflicted_commit
    materialized = merged.materialize_conflict(settings, "a.txt")

    tx = repo.start_transaction(settings)
    builder = tx.resolve_conflict(merged, "a.txt", materialized)
    builder.set_description("no-op resolve attempt")
    still_conflicted = builder.write(repo)

    assert still_conflicted.has_conflict


def test_resolve_conflict_on_non_conflicted_path_raises(conflicted_commit, settings):
    repo, merged = conflicted_commit
    tx = repo.start_transaction(settings)
    with pytest.raises(pyjj.JjError):
        tx.resolve_conflict(merged, "no-such-file.txt", b"anything")


@pytest.fixture
def three_way_conflicted_commit(workspace, repo, settings):
    """A merge commit with 3 parents whose a.txt conflicts 3 ways --
    exercises `materialize_conflict()`/`resolve_conflict()`'s multi-side
    (diff3-plus) rendering path, not just the simple 2-side case every
    other fixture here uses.
    """
    _write(workspace, "a.txt", "line1\nline2\nline3\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")

    sides = []
    for i, val in enumerate(["SIDE1", "SIDE2", "SIDE3"]):
        tx = repo.start_transaction(settings)
        seed = tx.new_commit(settings, [base.id])
        seed.set_description(f"side{i} seed")
        seed_commit = seed.write(repo)
        tx.set_wc_commit("default", seed_commit.id)
        tx.rebase_descendants()
        repo = tx.commit(f"advance to side{i}")
        workspace.check_out(repo, seed_commit)
        _write(workspace, "a.txt", f"line1\n{val}\nline3\n")
        repo, _ = workspace.snapshot(settings)
        sides.append(repo.resolve_single(settings, "@"))

    tx = repo.start_transaction(settings)
    merge_builder = tx.new_commit(settings, [s.id for s in sides])
    merge_builder.set_description("3-way merge")
    merge_commit = merge_builder.write(repo)
    tx.set_wc_commit("default", merge_commit.id)
    tx.rebase_descendants()
    repo2 = tx.commit("create 3-way conflict")

    return repo2, repo2.resolve_single(settings, "@")


def test_materialize_conflict_three_sides(three_way_conflicted_commit, settings):
    repo, merged = three_way_conflicted_commit
    assert merged.has_conflict
    assert len(merged.parent_ids) == 3

    text = merged.materialize_conflict(settings, "a.txt")
    assert text.startswith(b"line1\n")
    assert text.endswith(b"line3\n")
    assert b"SIDE1" in text
    assert b"SIDE2" in text
    assert b"SIDE3" in text


def test_resolve_conflict_three_sides_fully(three_way_conflicted_commit, settings):
    repo, merged = three_way_conflicted_commit
    tx = repo.start_transaction(settings)
    resolved_content = b"line1\nALL-THREE-MERGED\nline3\n"
    builder = tx.resolve_conflict(merged, "a.txt", resolved_content)
    resolved = builder.write(repo)
    tx.rebase_descendants()
    tx.commit("resolve 3-way conflict")

    assert not resolved.has_conflict
    assert resolved.read_file("a.txt") == resolved_content


@pytest.fixture
def _conflicted_commit_with_marker_style(tmp_path, monkeypatch):
    """Same conflict scenario as `conflicted_commit`, but parameterized by
    `ui.conflict-marker-style`, which `materialize_conflict()` reads from
    `settings` -- mirrors jj_lib's own ConflictMarkerStyle-parametrized
    materialize tests in lib/tests/test_conflicts.rs.
    """

    def make(style):
        config_file = tmp_path / "config.toml"
        config_file.write_text(f"""
[user]
name = "Test User"
email = "test@example.com"

[ui]
conflict-marker-style = "{style}"
""")
        monkeypatch.setenv("JJ_CONFIG", str(config_file))
        monkeypatch.delenv("JJ_USER", raising=False)
        monkeypatch.delenv("JJ_EMAIL", raising=False)
        settings = pyjj.UserSettings()

        workspace_root = tmp_path / f"repo-{style}"
        workspace_root.mkdir()
        ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))
        _write(ws, "a.txt", "line1\nline2\nline3\n")
        repo, _ = ws.snapshot(settings)
        base = repo.resolve_single(settings, "@")

        tx = repo.start_transaction(settings)
        seed = tx.new_commit(settings, [base.id])
        side1_seed = seed.write(repo)
        tx.set_wc_commit("default", side1_seed.id)
        tx.rebase_descendants()
        repo = tx.commit("advance to side1")
        ws.check_out(repo, side1_seed)
        _write(ws, "a.txt", "line1\nSIDE1\nline3\n")
        repo, _ = ws.snapshot(settings)
        side1 = repo.resolve_single(settings, "@")

        tx = repo.start_transaction(settings)
        seed2 = tx.new_commit(settings, [base.id])
        side2_seed = seed2.write(repo)
        tx.rebase_descendants()
        repo = tx.commit("advance to side2 seed")
        ws.check_out(repo, side2_seed)
        _write(ws, "a.txt", "line1\nSIDE2\nline3\n")
        repo, _ = ws.snapshot(settings)
        side2 = repo.resolve_single(settings, "@")

        tx = repo.start_transaction(settings)
        merge_builder = tx.new_commit(settings, [side1.id, side2.id])
        merge_commit = merge_builder.write(repo)
        tx.set_wc_commit("default", merge_commit.id)
        tx.rebase_descendants()
        repo2 = tx.commit("create merge conflict")

        return settings, repo2.resolve_single(settings, "@")

    return make


@pytest.mark.parametrize("style", ["diff", "snapshot", "git"])
def test_materialize_conflict_honors_marker_style(_conflicted_commit_with_marker_style, style):
    settings, merged = _conflicted_commit_with_marker_style(style)
    text = merged.materialize_conflict(settings, "a.txt")
    assert b"<<<<<<<" in text
    assert b">>>>>>>" in text
    assert b"SIDE1" in text
    assert b"SIDE2" in text


def test_materialize_conflict_marker_styles_produce_different_output(
    _conflicted_commit_with_marker_style,
):
    diff_settings, diff_merged = _conflicted_commit_with_marker_style("diff")
    git_settings, git_merged = _conflicted_commit_with_marker_style("git")

    diff_text = diff_merged.materialize_conflict(diff_settings, "a.txt")
    git_text = git_merged.materialize_conflict(git_settings, "a.txt")

    assert diff_text != git_text
    assert b"|||||||" in git_text
    assert b"|||||||" not in diff_text


def test_check_out_writes_conflict_markers_to_disk(workspace, conflicted_commit, settings):
    """Checking out a conflicted commit materializes conflict-marker text
    onto the real working-copy file -- mirrors
    lib/tests/test_local_working_copy.rs's
    test_materialize_snapshot_conflicted_files' checkout half. No
    materialize_conflict() call needed; check_out() does this
    automatically for any conflicted path.
    """
    repo, merged = conflicted_commit
    workspace.check_out(repo, repo.get_commit(merged.id))

    disk_content = Path(workspace.workspace_root, "a.txt").read_text()
    assert "<<<<<<<" in disk_content
    assert ">>>>>>>" in disk_content
    assert "SIDE1" in disk_content
    assert "SIDE2" in disk_content


def test_snapshot_resolves_a_conflict_hand_edited_on_disk(workspace, conflicted_commit, settings):
    """The real `jj st`/`jj diff` workflow: hand-edit the conflict-marker
    text jj wrote to disk (no explicit Transaction.resolve_conflict() call
    at all), then snapshot -- the edit should be parsed back and resolve
    the conflict, exactly as if resolve_conflict() had been called. Mirrors
    test_materialize_snapshot_conflicted_files' edit-and-resnapshot half.
    """
    repo, merged = conflicted_commit
    workspace.check_out(repo, repo.get_commit(merged.id))

    _write(workspace, "a.txt", "line1\nSIDE1-AND-SIDE2-HANDEDIT\nline3\n")
    repo, _ = workspace.snapshot(settings)
    resolved = repo.resolve_single(settings, "@")

    assert not resolved.has_conflict
    assert resolved.read_file("a.txt") == b"line1\nSIDE1-AND-SIDE2-HANDEDIT\nline3\n"


def test_snapshot_of_untouched_materialized_conflict_stays_conflicted(
    workspace, conflicted_commit, settings
):
    repo, merged = conflicted_commit
    workspace.check_out(repo, repo.get_commit(merged.id))

    repo, _ = workspace.snapshot(settings)
    unchanged = repo.resolve_single(settings, "@")

    assert unchanged.has_conflict
