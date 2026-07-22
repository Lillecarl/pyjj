#!/usr/bin/env python3
"""pyjjui — a Textual TUI for Jujutsu VCS, built on pyjj."""

import argparse
import sys

import pyjj


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pyjjui",
        description="Jujutsu VCS — Textual TUI (pyjj bindings)",
    )
    parser.add_argument(
        "-R", "--repo", dest="repo", default=".", help="Path to the workspace (default: .)"
    )
    parser.add_argument(
        "-r", "--revset", dest="revset", default=None,
        help="Override the log revset (default: from `revsets.log` config)",
    )
    parser.add_argument("--version", action="store_true", help="Show version information")
    args = parser.parse_args()

    if args.version:
        print(f"pyjjui (pyjj {pyjj.__version__})")
        return 0

    settings = pyjj.UserSettings()
    workspace = pyjj.Workspace.load(settings, args.repo)

    from .app import PyjjuiApp

    revset = args.revset or settings.get_string("revsets.log")
    app = PyjjuiApp(workspace=workspace, settings=settings, revset=revset)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
