"""pyjj — pythonic API for Jujutsu VCS, built on pyjj_bindings."""

from __future__ import annotations

import pyjj_bindings as _bindings
from pyjj_bindings import *  # noqa: F403
from pyjj_bindings import __version__

from . import _async  # noqa: F401  (installs the *_async methods)
from . import hunk
from .session import Atomic, PyjjError, Repo, open

# The generated stub has no `__all__`; the module has one at runtime.
__all__ = [
    *_bindings.__all__,  # type: ignore[attr-defined]
    "Atomic", "PyjjError", "Repo", "__version__", "hunk", "open",
]
