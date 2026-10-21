"""crypto subcommand: version."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

if TYPE_CHECKING:
    import argparse

def version(args: argparse.Namespace) -> int:
    print("pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
