"""crypto subcommand: sign."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..common import (
    _require_signing_backend,
    _rewrite_signatures,
    command,
)

if TYPE_CHECKING:
    import argparse

@command
def sign(args: argparse.Namespace) -> int:
    return _rewrite_signatures(args, "sign", "force", signed_only=False,
                               pre_check=_require_signing_backend)
