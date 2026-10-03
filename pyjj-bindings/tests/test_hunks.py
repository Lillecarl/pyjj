"""Tests for changed_line_ranges(): the 1-based inclusive line ranges
`jj fix` hands a tool's `line-range-arg`. Cases mirror the real CLI's own
unit tests for compute_regions_to_format (cli/src/commands/fix.rs)."""

import pyjj_bindings as b


def test_none_base_means_the_whole_file():
    assert b.changed_line_ranges(None, b"a\nb\nc\n") == [(1, 3)]


def test_empty_base_means_the_whole_file():
    assert b.changed_line_ranges(b"", b"a\nb\nc\n") == [(1, 3)]


def test_modified_base_gives_the_changed_lines():
    assert b.changed_line_ranges(b"a\nB\nc\n", b"a\nb\nc\n") == [(2, 2)]


def test_deleted_lines_give_no_ranges():
    assert b.changed_line_ranges(b"a\nb\nc\nd\n", b"a\nb\nc\n") == []


def test_multiple_ranges():
    assert b.changed_line_ranges(b"A\nb\nC\n", b"a\nb\nc\n") == [(1, 1), (3, 3)]


def test_empty_current_gives_no_ranges():
    assert b.changed_line_ranges(b"a\nb\nc\n", b"") == []


def test_identical_content_gives_no_ranges():
    assert b.changed_line_ranges(b"a\nb\n", b"a\nb\n") == []


def test_missing_trailing_newline_counts_the_last_line():
    assert b.changed_line_ranges(None, b"a\nb") == [(1, 2)]
