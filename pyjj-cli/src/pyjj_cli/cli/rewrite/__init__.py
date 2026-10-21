from __future__ import annotations

from typing import TYPE_CHECKING

# cli/rewrite package — one module per subcommand, mirroring commands/rewrite/.
# Keeps each parser small and avoids the old 66-line/9-parser monolith.
from . import (
    abandon,
    absorb,
    duplicate,
    fix,
    rebase,
    restore,
    revert,
    simplify_parents,
    split,
    squash,
)

if TYPE_CHECKING:
    import argparse


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    squash.register(sub)
    rebase.register(sub)
    absorb.register(sub)
    fix.register(sub)
    revert.register(sub)
    abandon.register(sub)
    duplicate.register(sub)
    restore.register(sub)
    split.register(sub)
    simplify_parents.register(sub)
