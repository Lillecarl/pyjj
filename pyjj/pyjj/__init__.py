"""pyjj — pythonic API for Jujutsu VCS, built on pyjj_bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj_bindings as _bindings
from pyjj_bindings import *  # noqa: F403
from pyjj_bindings import __version__ as __version__

from . import hunk as hunk
from .session import AsyncAtomic as AsyncAtomic
from .session import Atomic as Atomic
from .session import PyjjError as PyjjError
from .session import Repo as Repo
from .session import open as open
from .session import open_async as open_async

# Type checkers take the public names; a computed `__all__` would hide them.
if not TYPE_CHECKING:
    __all__ = [*_bindings.__all__, "AsyncAtomic", "Atomic", "PyjjError", "Repo", "hunk", "open",
                "open_async"]
