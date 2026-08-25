#!/usr/bin/env python3
"""One pyjj-cli invocation per process, driven by parity_harness.RepoPair.

The driver executes `pyjj_cli.main()` with a jj-dialect argv, exactly as
the scenario names it — so every argument shape and flag the scenarios
use must exist in pyjj-cli's parser for parity to pass. A fresh
interpreter per invocation mirrors the `jj` CLI's process-per-command
model, which is what keeps the seeded RNG streams of the two sides
aligned (see harness module docs). The parent passes the pinned
environment; machine config is suppressed via the scratch HOME.
"""

from __future__ import annotations

import sys

import pyjj_cli.__main__


def main() -> int:
    repo_path = sys.argv[1]
    argv = sys.argv[2:]
    # The console entry point, minus the wrapper: same argparse surface.
    return pyjj_cli.__main__.main(["-R", repo_path, *argv])


if __name__ == "__main__":
    sys.exit(main())
