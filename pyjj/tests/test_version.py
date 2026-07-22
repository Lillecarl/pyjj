"""Sanity check that the pyjj wrapper re-exports version info correctly."""

import pyjj


def test_version_attrs_agree():
    assert pyjj.VERSION == pyjj.__version__
    assert pyjj.VERSION  # non-empty
