"""pyjj — pythonic API for Jujutsu VCS, built on pyjj_bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj_bindings as _bindings
from pyjj_bindings import *  # noqa: F403
from pyjj_bindings import __version__ as __version__

from . import hunk
from .session import Atomic, PyjjError, Repo, open

# Type checkers take the public names; a computed `__all__` would hide them.
if not TYPE_CHECKING:
    __all__ = [*_bindings.__all__, "Atomic", "PyjjError", "Repo", "hunk", "open"]
