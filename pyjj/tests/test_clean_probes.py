"""Workspace.has_unrecorded_changes() and ReadonlyRepo.contains_changes():
the two read-only probes `pyjj workspace clean` decides with."""

from pathlib import Path


def _write(workspace, name, content):
    Path(workspace.workspace_root, name).write_text(content)


def _head_op(workspace):
    return workspace.load_at_head().operation.id


def test_unrecorded_changes_follow_the_disk(workspace, settings):
    assert workspace.has_unrecorded_changes(settings) is False
    _write(workspace, "a.txt", "a\n")
    before = _head_op(workspace)
    assert workspace.has_unrecorded_changes(settings) is True
    assert _head_op(workspace) == before
    workspace.snapshot(settings)
    assert workspace.has_unrecorded_changes(settings) is False


def test_unrecorded_changes_answer_for_a_stale_working_copy(workspace, settings):
    _write(workspace, "a.txt", "a\n")
    repo, _ = workspace.snapshot(settings)
    root = repo.resolve_single(settings, "root()")
    tx = repo.start_transaction(settings)
    moved = tx.new_commit(settings, [root.id]).write(repo)
    tx.set_wc_commit("default", moved.id)
    tx.rebase_descendants()
    tx.commit("move the working copy elsewhere")
    assert workspace.has_unrecorded_changes(settings) is False
    _write(workspace, "a.txt", "edited\n")
    assert workspace.has_unrecorded_changes(settings) is True
    with_stale = workspace.load_at_head()
    assert with_stale.resolve_single(settings, "@").id == moved.id


def _commit_with(workspace, settings, files):
    for name, content in files.items():
        _write(workspace, name, content)
    repo, _ = workspace.snapshot(settings)
    commit = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    tx.new_commit(settings, [commit.id]).write(repo)
    tx.commit("new")
    return commit


def test_contains_changes(workspace, settings):
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "root()")
    ab = _commit_with(workspace, settings, {"a.txt": "a\n", "b.txt": "b\n"})
    abc = _commit_with(workspace, settings, {"c.txt": "c\n"})
    repo = workspace.load_at_head()
    assert repo.contains_changes(abc, root, ab) is True
    assert repo.contains_changes(ab, root, abc) is False
    assert repo.contains_changes(abc, root, root) is False


def test_contains_changes_needs_a_resolved_match(workspace, settings):
    a = _commit_with(workspace, settings, {"a.txt": "one\n"})
    other = _commit_with(workspace, settings, {"a.txt": "two\n"})
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "root()")
    assert repo.contains_changes(other, root, a) is False
