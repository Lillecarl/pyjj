"""Agent-oriented hunk specs (hunk-level + line-level) via pyjj.hunk and CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pyjj
import pyjj.hunk as hunk_mod
import pyjj_bindings
import pytest


def _select(before, after, file_spec, default="reset"):
    spec = hunk_mod.parse_spec(json.dumps({"files": {"f": file_spec}, "default": default}))
    return hunk_mod.select_content("f", before, after, spec.files["f"], spec.default)


def test_indices_follow_jjs_line_diff():
    before = b"a\nb\nc\nd\ne\n"
    after = b"a\nB\nc\nX\nY\ne\n"
    ours = hunk_mod.get_hunks(before, after)
    jj = pyjj_bindings.diff_hunks(before, after)
    assert [(h.index, h.removed, h.added) for h in ours] == [
        (h.index, h.before, h.after) for h in jj]
    assert [(h.before.start, h.after.start) for h in ours] == [(2, 2), (4, 4)]


def test_lines_of_a_hunk_selected_by_id():
    before, after = b"base\n", b"base\na\nb\nc\n"
    hunk_id = hunk_mod.get_hunks(before, after)[0].id
    assert _select(before, after, {"hunks": [{"id": hunk_id, "lines": [1]}]}) == b"base\nb\n"


def test_a_partial_replace_keeps_the_removed_lines_not_chosen():
    before, after = b"old1\nold2\n", b"new1\nnew2\n"
    assert _select(before, after, {"hunks": [{"index": 0, "added": [0]}]}) == b"old1\nold2\nnew1\n"
    assert _select(before, after, {"hunks": [{"index": 0, "added": [0], "removed": [1]}]}) == b"old1\nnew1\n"


def test_removed_lines_are_the_lines_dropped():
    before, after = b"a\nb\nc\n", b"a\n"
    assert _select(before, after, {"hunks": [{"index": 0, "removed": [0]}]}) == b"a\nc\n"
    assert _select(before, after, {"hunks": [{"index": 0, "lines": [1]}]}) == b"a\nb\n"


def test_a_line_range_matches_a_deletion_by_its_old_lines():
    before, after = b"a\nb\nc\n", b"a\nc\n"
    assert _select(before, after, {"lines": [[2, 3]]}) == after


def test_an_empty_line_range_is_refused():
    with pytest.raises(ValueError, match="empty"):
        hunk_mod.parse_spec(json.dumps({"files": {"f": {"lines": [[2, 2]]}}}))


def test_a_bool_is_not_an_index():
    with pytest.raises(ValueError):
        hunk_mod.parse_spec(json.dumps({"files": {"f": {"hunks": [True]}}}))


def test_an_unknown_hunk_is_refused():
    with pytest.raises(ValueError, match="no hunk 3"):
        _select(b"a\n", b"b\n", {"hunks": [3]})


def test_a_hunk_selection_on_a_binary_file_is_refused():
    with pytest.raises(ValueError, match="binary"):
        _select(b"\xff\x00", b"\xfe\x00", {"hunks": [0]})


def test_a_kept_deletion_stays_a_deletion():
    assert _select(b"gone\n", None, {"action": "keep"}) is None
    assert _select(b"gone\n", None, {"hunks": [0]}) is None
    assert hunk_mod.select_content("f", b"gone\n", None, None, "keep") is None


def test_an_added_file_with_nothing_chosen_stays_absent():
    assert _select(None, b"a\nb\n", {"hunks": [{"index": 0, "added": []}]}) is None
    assert _select(None, b"a\nb\n", {"hunks": [{"index": 0, "added": [1]}]}) == b"b\n"


def test_action_with_hunks_is_refused():
    with pytest.raises(ValueError, match="action"):
        hunk_mod.parse_spec(json.dumps({"files": {"f": {"action": "keep", "hunks": [0]}}}))


def test_spec_roundtrip_with_ids(workspace, repo, settings):
    # Create a base file with hunks, then verify id-based spec works
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("line1\nline2\nline3\nline4\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [base.id])
    b.set_description("child")
    child = b.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("child")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("LINE1\nline2\nLINE3\nline4\nline5\n")
    repo, _ = workspace.snapshot(settings)
    changed = repo.resolve_single(settings, "@")

    file_contents = hunk_mod.collect_file_contents_for_commit(repo, changed)
    before, after = file_contents["a.txt"]
    hunks = hunk_mod.get_hunks(before, after)
    # Use id of first hunk
    first_id = hunks[0].id
    spec = hunk_mod.parse_spec(
        json.dumps({"files": {"a.txt": {"ids": [first_id]}}, "default": "reset"})
    )
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec)
    assert "a.txt" in overrides
    assert overrides["a.txt"] == b"LINE1\nline2\nline3\nline4\n"


def test_line_range_selects_overlapping_hunk(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("line1\nline2\nline3\nline4\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [base.id])
    b.set_description("child")
    child = b.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("child")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("LINE1\nline2\nLINE3\nline4\nline5\n")
    repo, _ = workspace.snapshot(settings)
    changed = repo.resolve_single(settings, "@")

    # line range [1,2] should select hunk at after line 1 (LINE1)
    spec = hunk_mod.parse_spec(
        json.dumps({"files": {"a.txt": {"lines": [[1, 2]]}}, "default": "reset"})
    )
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec)
    assert overrides["a.txt"] == b"LINE1\nline2\nline3\nline4\n"


def test_per_hunk_line_filter_for_insert(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("base\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [base.id])
    b.set_description("child")
    child = b.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("child")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("base\na\nb\nc\n")
    repo, _ = workspace.snapshot(settings)
    changed = repo.resolve_single(settings, "@")

    # Single insert hunk with 3 added lines, select lines 0 and 2 -> a and c
    spec = hunk_mod.parse_spec(
        json.dumps({"files": {"a.txt": {"hunks": [{"index": 0, "lines": [0, 2]}]}}, "default": "reset"})
    )
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec)
    assert overrides["a.txt"] == b"base\na\nc\n"


def test_pydantic_validation_rejects_bad_id(workspace, repo, settings):
    try:
        hunk_mod.parse_spec(
            json.dumps({"files": {"a.txt": {"hunks": ["hunk-xyz"]}}, "default": "reset"})
        )
        assert False, "should have raised"
    except ValueError as e:
        assert "hunk" in str(e).lower()


def test_cli_hunk_list_and_split(workspace, repo, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("line1\nline2\nline3\nline4\n")
    repo, _ = workspace.snapshot(settings)
    base = repo.resolve_single(settings, "@")
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [base.id])
    b.set_description("child")
    child = b.write(repo)
    tx.set_wc_commit("default", child.id)
    tx.rebase_descendants()
    repo = tx.commit("child")
    workspace.check_out(repo, child)
    (root / "a.txt").write_text("LINE1\nline2\nLINE3\nline4\nline5\n")
    repo, _ = workspace.snapshot(settings)
    changed = repo.resolve_single(settings, "@")

    # Use CLI hunk list to get an id, then split via that id
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(workspace.workspace_root), "hunk", "list", "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    first_id = data["files"][0]["hunks"][0]["id"]

    spec = json.dumps({"files": {"a.txt": {"ids": [first_id]}}, "default": "reset"})
    result2 = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(workspace.workspace_root), "hunk", "split", "-r", changed.id.hex(), spec, "split via id"],
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0, result2.stderr
    repo = workspace.load_at_head()
    # Find the split commit
    commits = list(repo.revset(settings, "all()"))
    descs = [c.description for c in commits]
    assert any("split via id" in d for d in descs)


def _cli(workspace, *args):
    return subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(workspace.workspace_root), *args],
        capture_output=True, text=True)


def test_cli_hunk_commit_takes_spec_by_flag_then_message(workspace, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("a\n")
    (root / "b.txt").write_text("b\n")
    spec = json.dumps({"files": {"a.txt": {"action": "keep"}}})
    result = _cli(workspace, "hunk", "commit", "--spec", spec, "only a")
    assert result.returncode == 0, result.stderr
    repo = workspace.load_at_head()
    committed = repo.resolve_single(settings, "@-")
    assert committed.description.strip() == "only a"
    assert committed.file_exists("a.txt") and not committed.file_exists("b.txt")


def test_cli_hunk_squash_moves_chosen_lines_into_the_parent(workspace, settings):
    root = Path(workspace.workspace_root)
    (root / "a.txt").write_text("base\n")
    assert _cli(workspace, "commit", "-m", "base").returncode == 0
    (root / "a.txt").write_text("base\none\ntwo\n")
    spec = json.dumps({"files": {"a.txt": {"hunks": [{"index": 0, "lines": [1]}]}}})
    result = _cli(workspace, "hunk", "squash", spec)
    assert result.returncode == 0, result.stderr
    repo = workspace.load_at_head()
    assert repo.resolve_single(settings, "@-").read_file("a.txt") == b"base\ntwo\n"
    assert repo.resolve_single(settings, "@").read_file("a.txt") == b"base\none\ntwo\n"
