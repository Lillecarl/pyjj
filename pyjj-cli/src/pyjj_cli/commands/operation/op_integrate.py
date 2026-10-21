"""operation subcommand: op_integrate."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def op_integrate(args: argparse.Namespace) -> int:
    print("Error: op integrate is not yet supported", file=sys.stderr)
    return 2
