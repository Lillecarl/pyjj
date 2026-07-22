"""Unit tests for the exception hierarchy.

JjError and its subclasses need an explicit Rust-side `#[new]` to be safely
constructible/raisable — without it, CPython's error-normalization machinery
can crash with `TypeError: cannot create ... instances` instead of raising
the real error. These tests pin that down.
"""

import pytest

import pyjj_bindings as b

SUBCLASSES = [
    b.RepoInitError,
    b.RepoLoadError,
    b.BackendError,
    b.IndexError,
    b.TransactionError,
    b.WorkspaceInitError,
    b.WorkspaceLoadError,
    b.WorkingCopyError,
    b.CheckoutError,
    b.RevsetParseError,
    b.RevsetEvalError,
    b.GitImportError,
    b.GitExportError,
    b.GitFetchError,
    b.GitPushError,
]


def test_jjerror_is_an_exception():
    assert issubclass(b.JjError, Exception)


def test_jjerror_constructible_and_raisable():
    err = b.JjError("boom")
    assert err.message == "boom"
    try:
        raise err
    except b.JjError as caught:
        assert caught.message == "boom"


def test_jjerror_str_uses_python_exception_args():
    # BaseException.__new__ stores the positional arg(s) as .args, and the
    # default __str__ renders that — independent of the custom .message
    # field.
    err = b.JjError("boom")
    assert str(err) == "boom"


@pytest.mark.parametrize("cls", SUBCLASSES)
def test_subclass_is_a_jjerror(cls):
    assert issubclass(cls, b.JjError)


@pytest.mark.parametrize("cls", SUBCLASSES)
def test_subclass_constructible_and_raisable(cls):
    err = cls("specific message")
    assert err.message == "specific message"
    assert isinstance(err, b.JjError)
    try:
        raise err
    except b.JjError as caught:
        assert caught.message == "specific message"
        assert isinstance(caught, cls)
