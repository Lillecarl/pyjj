"""Tests for Commit.diff_stats() -- `jj diff --stat`'s numbers.

The counts follow jj's rule: every differing hunk contributes its left
lines to `removed` and its right lines to `added`. A replaced line
therefore counts once on each side, not as a single change.
"""

from pathlib import Path

import pyjj


def _commit(workspace, settings, files, message):
    for name, content in files.items():
        Path(workspace.workspace_root, name).write_bytes(content)
    repo, _stats = workspace.snapshot(settings)
    wc = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, wc)
    builder.set_description(message)
    written = builder.write(repo)
    tx.set_wc_commit("default", written.id)
    tx.rebase_descendants()
    return tx.commit(message), written


def test_added_file_counts_every_line(workspace, repo, settings, wc_commit):
    repo, before = _commit(workspace, settings, {}, "base")
    repo, after = _commit(workspace, settings,
                          {"a.txt": b"one\ntwo\nthree\n"}, "add")
    stats = before.diff_stats(after, settings)
    by_path = {s.path: s for s in stats}
    assert by_path["a.txt"].status == "added"
    assert by_path["a.txt"].added == 3
    assert by_path["a.txt"].removed == 0
    assert by_path["a.txt"].binary is False


def test_replaced_line_counts_on_both_sides(workspace, repo, settings, wc_commit):
    repo, before = _commit(workspace, settings,
                           {"a.txt": b"one\ntwo\nthree\n"}, "base")
    repo, after = _commit(workspace, settings,
                          {"a.txt": b"one\nTWO\nthree\n"}, "edit")
    stat = before.diff_stats(after, settings)[0]
    assert stat.status == "modified"
    assert (stat.added, stat.removed) == (1, 1)


def test_removed_file_counts_as_removed_lines(workspace, repo, settings,
                                              wc_commit):
    repo, before = _commit(workspace, settings, {"a.txt": b"x\ny\n"}, "base")
    Path(workspace.workspace_root, "a.txt").unlink()
    repo, after = _commit(workspace, settings, {}, "drop")
    stat = before.diff_stats(after, settings)[0]
    assert stat.status == "removed"
    assert (stat.added, stat.removed) == (0, 2)


def test_binary_file_reports_no_line_counts(workspace, repo, settings,
                                            wc_commit):
    """jj calls a file binary when a NUL appears in the first 8000 bytes."""
    repo, before = _commit(workspace, settings, {}, "base")
    repo, after = _commit(workspace, settings,
                          {"b.bin": b"\x00\x01\x02\x03"}, "add binary")
    stat = before.diff_stats(after, settings)[0]
    assert stat.binary is True
    assert stat.added is None and stat.removed is None
    assert stat.bytes_delta == 4


def test_bytes_delta_is_negative_when_a_file_shrinks(workspace, repo, settings,
                                                     wc_commit):
    repo, before = _commit(workspace, settings, {"a.txt": b"aaaaa\n"}, "base")
    repo, after = _commit(workspace, settings, {"a.txt": b"a\n"}, "shrink")
    stat = before.diff_stats(after, settings)[0]
    assert stat.bytes_delta == -4


def test_paths_restrict_the_stats(workspace, repo, settings, wc_commit):
    repo, before = _commit(workspace, settings, {}, "base")
    repo, after = _commit(workspace, settings,
                          {"a.txt": b"a\n", "b.txt": b"b\n"}, "two files")
    both = before.diff_stats(after, settings)
    assert {s.path for s in both} == {"a.txt", "b.txt"}
    only_a = before.diff_stats(after, settings, ["a.txt"])
    assert [s.path for s in only_a] == ["a.txt"]


def test_no_changes_gives_no_entries(workspace, repo, settings, wc_commit):
    repo, only = _commit(workspace, settings, {"a.txt": b"a\n"}, "base")
    assert only.diff_stats(only, settings) == []
