#!/usr/bin/env python3
"""pyjj-cli — Python CLI for Jujutsu VCS, backed by the pyjj Rust bindings."""
# PYTHON_ARGCOMPLETE_OK

import argparse
import sys

import argcomplete


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pyjj",
        description="Jujutsu VCS — Python CLI (pyjj bindings)",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a new jj repo")
    p_init.add_argument("path", nargs="?", help="Path to init (default: .)")

    # status
    p_status = sub.add_parser("status", help="Show working copy status")
    p_status.add_argument("path", nargs="?", help="Path to workspace")
    p_status.add_argument(
        "-R", "--repository", dest="repo", action="store_true",
        help="Operate on a repo directly (no working copy)",
    )

    # log
    p_log = sub.add_parser("log", help="Show commit history")
    p_log.add_argument("path", nargs="?", help="Path to workspace")
    p_log.add_argument(
        "-R", "--repository", dest="repo", action="store_true",
        help="Operate on a repo directly (no working copy)",
    )
    p_log.add_argument("-n", "--limit", type=int, default=10, help="Max commits to show")

    # describe
    p_describe = sub.add_parser("describe", help="Set working-copy commit description")
    p_describe.add_argument("message", nargs="+", help="Description text")
    p_describe.add_argument(
        "-R", "--repository", dest="repo", action="store_true",
        help="Operate on a repo directly (no working copy)",
    )
    p_describe.add_argument("path", nargs="?", help="Path to workspace")

    # version
    sub.add_parser("version", help="Show version information")

    # Completion runs the CLI itself on every <TAB>; keep everything heavy
    # (the pyjj bindings, via .commands) out of that path.
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    from .commands import describe, init, log, status, version

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "init": init,
        "status": status,
        "log": log,
        "describe": describe,
        "version": version,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
