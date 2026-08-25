#!/usr/bin/env python3
"""pyjj-cli — Python CLI for Jujutsu VCS, backed by the pyjj Rust bindings.

Command and argument shapes mirror the real `jj` CLI so that the parity
suite (pyjj/tests/parity) can run the same argv through both tools.
"""

import argparse
import sys

import argcomplete

# Imported after argcomplete.autocomplete() below: this pulls in pyjj and
# with it the Rust extension module, which must not load on every <TAB>.
from .commands import (
    abandon,
    bookmark,
    describe,
    duplicate,
    git_init,
    log,
    new,
    rebase,
    squash,
    status,
    version,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyjj",
        description="Jujutsu VCS — Python CLI (pyjj bindings)",
    )
    parser.add_argument(
        "-R", "--repository", dest="repository", default=".",
        help="Path to the workspace to operate on (default: .)",
    )
    sub = parser.add_subparsers(dest="command")

    # git
    p_git = sub.add_parser("git", help="Git interop commands")
    git_sub = p_git.add_subparsers(dest="git_command")
    p_ginit = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p_ginit.add_argument("destination", nargs="?", default=".", help="Destination directory")

    # status
    sub.add_parser("status", help="Show working copy status")

    # log
    p_log = sub.add_parser("log", help="Show commit history")
    p_log.add_argument("-n", "--limit", type=int, default=10, metavar="LIMIT",
                       help="Max commits to show (default: 10)")

    # describe: -r REVSETS, repeatable -m MESSAGE, --stdin
    p_desc = sub.add_parser("describe", aliases=["desc"], help="Set commit descriptions")
    p_desc.add_argument("-r", "--revision", dest="revisions_opt", action="append",
                        default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p_desc.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                        help="Revisions to describe (default: @)")
    p_desc.add_argument("-m", "--message", dest="messages", action="append",
                        default=None, metavar="MESSAGE",
                        help="Description text (repeatable; paragraphs joined)")
    p_desc.add_argument("--stdin", action="store_true",
                        help="Read description from stdin")

    # new
    p_new = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p_new.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                       help="Parent revisions (default: @)")
    p_new.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                       help="Description of the new change")

    # bookmark create/set
    p_bm = sub.add_parser("bookmark", help="Manage bookmarks")
    bm_sub = p_bm.add_subparsers(dest="bookmark_command")
    p_bmc = bm_sub.add_parser("create", help="Create a new bookmark")
    p_bmc.add_argument("names", nargs="+", metavar="NAMES")
    p_bmc.add_argument("-r", "--revision", default="@", metavar="REVSET",
                       help="Revision to point at (default: @)")
    p_bms = bm_sub.add_parser("set", help="Move an existing bookmark")
    p_bms.add_argument("name")
    p_bms.add_argument("-r", "--revision", required=True, metavar="REVSET")

    # squash
    p_sq = sub.add_parser("squash", help="Move changes from a revision into another")
    p_sq.add_argument("-r", "--revision", action="append", default=None,
                      metavar="REVSETS", help="Source revisions (default: @)")
    p_sq.add_argument("-f", "--from", dest="from_", action="append", default=None,
                      metavar="REVSETS", help="Source revisions")
    p_sq.add_argument("-t", "--into", dest="into", default=None, metavar="REVSET",
                      help="Destination revision (default: source's parent)")
    p_sq.add_argument("-u", "--use-destination-message", dest="use_destination_message",
                      action="store_true",
                      help="Keep destination's description unchanged")
    p_sq.add_argument("-m", "--message", dest="message", default=None, metavar="MESSAGE",
                      help="Description for the squashed revision")

    # rebase
    p_re = sub.add_parser("rebase", help="Move revisions to a different parent")
    p_re.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move (-r mode)")
    p_re.add_argument("-d", "--destination", dest="destinations", action="append",
                      required=True, metavar="REVSETS", help="New parent(s)")

    # abandon
    p_ab = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p_ab.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                      help="Revisions to abandon (default: @)")

    # duplicate
    p_dup = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p_dup.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                       help="Revisions to duplicate (default: @)")

    # version
    sub.add_parser("version", help="Show version information")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    # Completion runs the CLI itself on every <TAB>; keep everything heavy
    # out of that path.
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "git": lambda a: {"init": git_init}.get(a.git_command or "", _git_help)(a),
        "status": status,
        "log": log,
        "describe": describe,
        "new": new,
        "bookmark": lambda a: {"create": bookmark, "set": bookmark}.get(
            a.bookmark_command or "", _bm_help
        )(a),
        "squash": squash,
        "rebase": rebase,
        "abandon": abandon,
        "duplicate": duplicate,
        "version": version,
    }
    return commands[args.command](args)


def _git_help(args) -> int:
    print("usage: pyjj git {init}", file=sys.stderr)
    return 2


def _bm_help(args) -> int:
    print("usage: pyjj bookmark {create,set}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
