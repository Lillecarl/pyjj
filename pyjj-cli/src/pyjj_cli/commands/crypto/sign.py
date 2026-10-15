"""crypto subcommand: sign."""

from ..common import (
    _require_signing_backend,
    _rewrite_signatures,
    command,
)

@command
def sign(args) -> int:
    return _rewrite_signatures(args, "sign", "force", signed_only=False,
                               pre_check=_require_signing_backend)
