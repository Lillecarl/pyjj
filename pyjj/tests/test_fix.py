"""Tests for Transaction.fix_enumerate()/fix_apply(): jj fix equivalent.

Unlike `jj fix`'s CLI implementation (which plugs a `ParallelFileFixer` that
spawns formatter/linter subprocesses into jj_lib's `FileFixer` trait), pyjj
splits this into two data-in/data-out calls instead of a Python callback
into a Rust trait: `fix_enumerate()` returns the (deduplicated,
descendant-propagated) files that might need fixing as plain data, and
`fix_apply()` takes a `{key: new_content}` mapping computed by Python
(however it likes -- `subprocess`, a pure-Python transform, whatever) and
does the actual multi-commit rewrite/propagation. Same idiom `diff_hunks()`
+ `squash(hunks=...)` already use for interactive hunk selection.

Uses `pyjj.UserSettings()` (real config loaded) since the default revset
(`"reachable(@, mutable())"`) is one of jj's bundled `revsets.toml` values --
same constraint as test_absorb.py.
"""

from pathlib import Path

import pyjj


def _new_child(repo, settings, ws, parent):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    child = builder.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("new child")
    ws.check_out(repo, child)
    return repo


def _describe(repo, settings, commit, description):
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, commit)
    builder.set_description(description)
    commit = builder.write(repo)
    tx.set_wc_commit("default", commit.id)
    tx.rebase_descendants()
    return tx.commit(description), commit


def test_fix_enumerate_returns_current_content_for_matching_files(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    path = Path(workspace_root, "a.txt")
    path.write_text("line1\nline2\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base commit")
    ws.check_out(repo, base)

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings, revset="@")

    assert len(files) == 1
    assert files[0].path == "a.txt"
    assert files[0].content == b"line1\nline2\n"


def test_fix_apply_rewrites_the_commit_and_reports_it_in_rewrites(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    path = Path(workspace_root, "a.txt")
    path.write_text("line1\nline2\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base commit")
    ws.check_out(repo, base)

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings, revset="@")
    fixes = {f.key: f.content.upper() for f in files}
    summary = tx.fix_apply(settings, fixes, revset="@")
    tx.rebase_descendants()
    new_repo = tx.commit("fix")

    assert summary.num_checked_commits == 1
    assert summary.num_fixed_commits == 1
    assert len(summary.rewrites) == 1
    (new_id,) = summary.rewrites.values()
    fixed = new_repo.get_commit(new_id)
    assert fixed.read_file("a.txt") == b"LINE1\nLINE2\n"


def test_fix_apply_leaves_files_missing_from_the_mapping_unchanged(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    Path(workspace_root, "a.txt").write_text("a\n")
    Path(workspace_root, "b.txt").write_text("b\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base commit")
    ws.check_out(repo, base)

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings, revset="@")
    fixes = {f.key: f.content.upper() for f in files if f.path == "a.txt"}
    summary = tx.fix_apply(settings, fixes, revset="@")
    tx.rebase_descendants()
    new_repo = tx.commit("fix a.txt only")

    (new_id,) = summary.rewrites.values()
    fixed = new_repo.get_commit(new_id)
    assert fixed.read_file("a.txt") == b"A\n"
    assert fixed.read_file("b.txt") == b"b\n"


def test_fix_propagates_to_a_descendant_that_did_not_touch_the_fixed_file(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    a_path = Path(workspace_root, "a.txt")
    b_path = Path(workspace_root, "b.txt")
    a_path.write_text("line1\n")
    b_path.write_text("unrelated\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base")
    ws.check_out(repo, base)

    repo = _new_child(repo, settings, ws, base)
    b_path.write_text("unrelated-changed\n")
    repo, _ = ws.snapshot(settings)
    child = repo.resolve_single(settings, "@")
    repo, child = _describe(repo, settings, child, "child")

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings, revset="description(exact:'base')")
    fixes = {f.key: f.content.upper() for f in files if f.path == "a.txt"}
    summary = tx.fix_apply(settings, fixes, revset="description(exact:'base')")
    tx.rebase_descendants()
    new_repo = tx.commit("fix")

    assert summary.num_fixed_commits == 2
    by_description = {
        new_repo.get_commit(new_id).description: new_repo.get_commit(new_id)
        for new_id in summary.rewrites.values()
    }
    assert by_description["base"].read_file("a.txt") == b"LINE1\n"
    assert by_description["child"].read_file("a.txt") == b"LINE1\n"
    assert by_description["child"].read_file("b.txt") == b"unrelated-changed\n"


def test_fix_enumerate_respects_a_paths_filter(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    Path(workspace_root, "a.txt").write_text("a\n")
    Path(workspace_root, "b.txt").write_text("b\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base commit")
    ws.check_out(repo, base)

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings, revset="@", paths=["a.txt"])

    assert [f.path for f in files] == ["a.txt"]


def test_fix_enumerate_defaults_to_reachable_from_working_copy_and_mutable(tmp_path):
    settings = pyjj.UserSettings()
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(workspace_root))

    Path(workspace_root, "a.txt").write_text("a\n")
    repo, _ = ws.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    repo, base = _describe(repo, settings, base, "base commit")
    ws.check_out(repo, base)

    tx = repo.start_transaction(settings)
    files = tx.fix_enumerate(settings)

    assert [f.path for f in files] == ["a.txt"]
