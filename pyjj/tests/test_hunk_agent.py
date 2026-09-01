"""Agent-oriented hunk specs (hunk-level + line-level) via pyjj.hunk and CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pyjj
import pyjj.hunk as hunk_mod


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

    file_contents = hunk_mod.collect_file_contents_for_commit(repo, changed, settings)
    before, after = file_contents["a.txt"]
    hunks = hunk_mod.get_hunks_detailed(before.decode(), after.decode())
    # Use id of first hunk
    first_id = hunks[0]["id"]
    spec = hunk_mod.parse_spec(
        json.dumps({"files": {"a.txt": {"ids": [first_id]}}, "default": "reset"})
    )
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec, settings)
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
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec, settings)
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
    overrides = hunk_mod.spec_to_overrides(repo, changed, spec, settings)
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
