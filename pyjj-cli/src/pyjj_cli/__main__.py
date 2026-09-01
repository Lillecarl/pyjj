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
    commit,
    describe,
    diffedit,
    duplicate,
    edit,
    git_init,
    hunk_commit,
    hunk_list,
    hunk_split,
    hunk_squash,
    log,
    new,
    op_restore,
    redo,
    resolve,
    restore,
    rebase,
    squash,
    split,
    status,
    undo,
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

    # edit
    p_edit = sub.add_parser("edit", help="Edit (check out) a specific revision")
    p_edit.add_argument("revision_pos", metavar="REVSETS",
                        help="The revision to edit")

    # commit
    p_com = sub.add_parser("commit",
                           help="Describe @ and create a new empty change on top")
    p_com.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description text")
    p_com.add_argument("--editor", action="store_true",
                       help="Open an editor to edit the description")
    p_com.add_argument("-i", "--interactive", action="store_true",
                       help="Interactively choose which changes to include")
    p_com.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor to use (implies --interactive)")
    p_com.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths staying in the current commit")

    # restore
    p_res = sub.add_parser("restore", help="Restore paths from another revision")
    p_res.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                       help="Revision to restore from (default: @-)")
    p_res.add_argument("--into", dest="into", default="@", metavar="REVSET",
                       help="Revision to restore into (default: @)")
    p_res.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths to restore (default: all)")

    # split
    p_spl = sub.add_parser("split", help="Split a revision in two")
    p_spl.add_argument("-r", "--revision", default=None, metavar="REVSETS",
                       help="Revision to split (default: @)")
    p_spl.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description of the first half")
    p_spl.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor for selecting changes (no FILESETS)")
    p_spl.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths going into the first half")

    # diffedit
    p_de = sub.add_parser("diffedit",
                          help="Edit the diff between two revisions in a diff editor")
    p_de.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                      help="Show the diff FROM this revision (default: @-)")
    p_de.add_argument("--to", dest="into", default="@", metavar="REVSET",
                      help="Apply edits TO this revision (default: @)")
    p_de.add_argument("--tool", default=None, metavar="NAME",
                      help="Diff editor to use")
    p_rslv = sub.add_parser("resolve",
                            help="Resolve conflicted files with an external merge tool")
    p_rslv.add_argument("-r", "--revision", default="@", metavar="REVSET",
                        help="The revision to resolve conflicts in (default: @)")
    p_rslv.add_argument("-l", "--list", dest="list_", action="store_true",
                        help="Instead of resolving conflicts, list all the conflicts")
    p_rslv.add_argument("--tool", default=None, metavar="NAME",
                        help="3-way merge tool to be used; :ours and :theirs pick side #1/#2")
    p_rslv.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                        help="Only resolve conflicts in these paths")

    # hunk (AI agent granular selection)
    p_hunk = sub.add_parser("hunk", help="Hunk-level selection for AI agents (like jj-hunk)")
    hunk_sub = p_hunk.add_subparsers(dest="hunk_command")
    p_hunk_list = hunk_sub.add_parser("list", help="List hunks for a revision")
    p_hunk_list.add_argument("-r", "--revision", default="@", metavar="REVSET",
                             help="Revision to list hunks for (default: @)")
    p_hunk_list.add_argument("--format", choices=["json", "yaml", "text"], default="json",
                             help="Output format (default: json)")
    p_hunk_split = hunk_sub.add_parser("split", help="Split a revision with hunk/line spec")
    p_hunk_split.add_argument("-r", "--revision", default="@", metavar="REVSET",
                              help="Revision to split (default: @)")
    p_hunk_split.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                              help="Read spec from file (JSON/YAML)")
    p_hunk_split.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_split.add_argument("message", nargs="?", help="Commit message for first half")
    p_hunk_commit = hunk_sub.add_parser("commit", help="Commit selected hunks from working copy")
    p_hunk_commit.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_commit.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_commit.add_argument("message", nargs="?", help="Commit message")
    p_hunk_squash = hunk_sub.add_parser("squash", help="Squash selected hunks into parent")
    p_hunk_squash.add_argument("-r", "--revision", default="@", metavar="REVSET",
                               help="Revision to squash (default: @)")
    p_hunk_squash.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_squash.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")

    # operation-level
    sub.add_parser("undo", help="Undo the last operation")
    sub.add_parser("redo", help="Redo a previously undone operation")
    p_op = sub.add_parser("op", help="Operation log commands")
    op_sub = p_op.add_subparsers(dest="op_command")
    p_opr = op_sub.add_parser("restore", help="Restore to the state of an operation")
    p_opr.add_argument("operation_pos", metavar="OPERATION",
                       help="The operation to restore to")

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
        "edit": edit,
        "commit": commit,
        "restore": restore,
        "split": split,
        "diffedit": diffedit,
        "resolve": resolve,
        "hunk": lambda a: {
            "list": hunk_list,
            "split": hunk_split,
            "commit": hunk_commit,
            "squash": hunk_squash,
        }.get(a.hunk_command or "", _hunk_help)(a),
        "undo": undo,
        "redo": redo,
        "op": lambda a: {"restore": op_restore}.get(a.op_command or "", _op_help)(a),
        "version": version,
    }
    return commands[args.command](args)


def _git_help(args) -> int:
    print("usage: pyjj git {init}", file=sys.stderr)
    return 2


def _bm_help(args) -> int:
    print("usage: pyjj bookmark {create,set}", file=sys.stderr)
    return 2


def _op_help(args) -> int:
    print("usage: pyjj op {restore}", file=sys.stderr)
    return 2


def _hunk_help(args) -> int:
    print("usage: pyjj hunk {list,split,commit,squash}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
