"""Sanity checks on the module surface itself."""

import pyjj_bindings as b


def test_version_attrs_agree():
    assert b.VERSION == b.__version__
    assert isinstance(b.VERSION, str)
    assert b.VERSION  # non-empty
