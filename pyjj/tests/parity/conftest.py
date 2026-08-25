"""Fixtures for the parity suite."""

from pathlib import Path

import pytest

from parity_harness import RepoPair


@pytest.fixture
def pair(tmp_path: Path) -> RepoPair:
    return RepoPair(tmp_path)
