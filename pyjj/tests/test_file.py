"""Tests for Commit.read_file()/file_exists()."""

from pathlib import Path

import pytest

import pyjj


def test_file_does_not_exist(wc_commit):
    assert not wc_commit.file_exists("nope.txt")
    with pytest.raises(pyjj.JjError):
        wc_commit.read_file("nope.txt")


def test_read_file_content(workspace, settings):
    Path(workspace.workspace_root, "hello.txt").write_text("hi there\n")
    new_repo, _stats = workspace.snapshot(settings)
    commit = new_repo.resolve_single(settings, "@")

    assert commit.file_exists("hello.txt")
    assert commit.read_file("hello.txt") == b"hi there\n"


def test_read_file_at_nested_path(workspace, settings):
    nested = Path(workspace.workspace_root, "a", "b")
    nested.mkdir(parents=True)
    (nested / "c.txt").write_bytes(b"\x00binary-ish\x01")
    new_repo, _stats = workspace.snapshot(settings)
    commit = new_repo.resolve_single(settings, "@")

    assert commit.read_file("a/b/c.txt") == b"\x00binary-ish\x01"


def test_reading_a_directory_raises(workspace, settings):
    nested = Path(workspace.workspace_root, "a")
    nested.mkdir()
    (nested / "c.txt").write_text("x\n")
    new_repo, _stats = workspace.snapshot(settings)
    commit = new_repo.resolve_single(settings, "@")

    assert not commit.file_exists("a")
    with pytest.raises(pyjj.JjError):
        commit.read_file("a")


def test_symlink_read_file_returns_target_as_bytes(workspace, settings):
    Path(workspace.workspace_root, "target.txt").write_text("hello\n")
    Path(workspace.workspace_root, "link").symlink_to("target.txt")
    new_repo, _stats = workspace.snapshot(settings)
    commit = new_repo.resolve_single(settings, "@")

    assert commit.file_exists("link")
    assert commit.read_file("link") == b"target.txt"
    assert commit.is_executable("link") is None
