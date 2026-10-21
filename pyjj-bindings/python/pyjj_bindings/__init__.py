"""Python bindings for Jujutsu VCS: the `_native` extension, plus the
`*_async` siblings `_async` installs on its classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _async  # noqa: F401  (installs the *_async methods)
from . import _native
from ._native import *  # noqa: F403
from ._native import __version__ as __version__

# Type checkers take the public names of the stub; a computed `__all__`
# would hide them all.
if not TYPE_CHECKING:
    __all__ = [*_native.__all__, "__version__"]
