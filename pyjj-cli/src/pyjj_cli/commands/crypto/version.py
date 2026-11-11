"""crypto subcommand: version."""

from __future__ import annotations

import sys
from importlib import resources
from typing import TYPE_CHECKING

import pyjj

if TYPE_CHECKING:
    import argparse


def build_rev() -> str | None:
    """The source revision the package build recorded in `build_rev.txt`.

    An editable install has no such file, and neither does a build from a
    tree with no revision to name.
    """
    try:
        rev = resources.files("pyjj_cli").joinpath("build_rev.txt").read_text().strip()
    except (FileNotFoundError, OSError):
        return None
    return rev or None


def version(args: argparse.Namespace) -> int:
    rev = build_rev()
    # jj appends its commit id the same way: `jj 0.47.1-d16ee1fc...`.
    print(f"pyjj-cli v0.1.0-{rev}" if rev else "pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
