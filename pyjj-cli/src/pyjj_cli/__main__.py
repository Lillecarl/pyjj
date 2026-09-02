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
    absorb,
    bookmark,
    commit,
    describe,
    diff,
    diffedit,
    duplicate,
    edit,
    file_annotate,
    file_list,
    file_show,
    git_init,
    hunk_commit,
    hunk_list,
    hunk_schema,
    hunk_split,
    hunk_squash,
    log,
    new,
    op_restore,
    redo,
    resolve,
    restore,
    rebase,
    show,
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
    p_log.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                       help="Which revisions to show (revset)")
    p_log.add_argument("-n", "--limit", type=int, default=10, metavar="LIMIT",
                       help="Max commits to show (default: 10)")
    p_log.add_argument("-G", "--no-graph", action="store_true", help="Don't show the graph")
    p_log.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                       help=argparse.SUPPRESS)
    p_log.add_argument("-p", "--patch", action="store_true", help="Show patch")
    p_log.add_argument("filesets", nargs="*", metavar="FILESETS", help=argparse.SUPPRESS)

    # diff
    p_diff = sub.add_parser("diff", help="Compare file contents between two revisions")
    p_diff.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                        help="Show changes in these revisions")
    p_diff.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSET",
                        help="Show changes from this revision")
    p_diff.add_argument("-t", "--to", dest="to", default=None, metavar="REVSET",
                        help="Show changes to this revision")
    p_diff.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_diff.add_argument("--stat", action="store_true", help="Show histogram")
    p_diff.add_argument("--name-only", action="store_true", help="Show only path")
    p_diff.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_diff.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_diff.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict diff to")

    # show
    p_show = sub.add_parser("show", help="Show revision metadata and diff")
    p_show.add_argument("revisions", nargs="*", metavar="REVSETS", help="Revisions to show (default: @)")
    p_show.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_show.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_show.add_argument("--stat", action="store_true", help="Show histogram")
    p_show.add_argument("--name-only", action="store_true", help="Show only path")
    p_show.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_show.add_argument("--no-patch", action="store_true", help="Do not show patch")

    # file
    p_file = sub.add_parser("file", help="File operations")
    file_sub = p_file.add_subparsers(dest="file_command")
    p_flist = file_sub.add_parser("list", help="List files in a revision")
    p_flist.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to list files for (default: @)")
    p_flist.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict to")
    p_fshow = file_sub.add_parser("show", help="Print contents of files in a revision")
    p_fshow.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to show files from (default: @)")
    p_fshow.add_argument("filesets", nargs="+", metavar="FILESETS", help="Paths to show")
    p_fannot = file_sub.add_parser("annotate", help="Show line annotation (blame)")
    p_fannot.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                          help="Revision to annotate (default: @)")
    p_fannot.add_argument("path", metavar="PATH", help="File to annotate")

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

    # bookmark create/set/delete/forget/list/move/rename
    p_bm = sub.add_parser("bookmark", help="Manage bookmarks")
    bm_sub = p_bm.add_subparsers(dest="bookmark_command")
    p_bmc = bm_sub.add_parser("create", help="Create a new bookmark")
    p_bmc.add_argument("names", nargs="+", metavar="NAMES")
    p_bmc.add_argument("-r", "--revision", default="@", metavar="REVSET",
                       help="Revision to point at (default: @)")
    p_bms = bm_sub.add_parser("set", help="Move an existing bookmark")
    p_bms.add_argument("name")
    p_bms.add_argument("-r", "--revision", required=True, metavar="REVSET")
    p_bmd = bm_sub.add_parser("delete", help="Delete a bookmark")
    p_bmd.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to delete")
    p_bmf = bm_sub.add_parser("forget", help="Forget a bookmark")
    p_bmf.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to forget")
    p_bml = bm_sub.add_parser("list", help="List bookmarks")
    p_bml.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to list")
    p_bml.add_argument("-a", "--all-remotes", action="store_true", help=argparse.SUPPRESS)
    p_bmm = bm_sub.add_parser("move", help="Move bookmarks to a revision")
    p_bmm.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to move")
    p_bmm.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSETS",
                       help=argparse.SUPPRESS)
    p_bmm.add_argument("-t", "--to", dest="to", default="@", metavar="REVSET",
                       help="Target revision (default: @)")
    p_bmr = bm_sub.add_parser("rename", help="Rename a bookmark")
    p_bmr.add_argument("old", metavar="OLD", help="Old bookmark name")
    p_bmr.add_argument("new", metavar="NEW", help="New bookmark name")

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
    p_sq.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to squash (default: all)")

    # rebase
    p_re = sub.add_parser("rebase", help="Move revisions to a different parent")
    p_re.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move (-r mode)")
    p_re.add_argument("-s", "--source", dest="sources", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move with descendants (-s mode)")
    p_re.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                      metavar="REVSETS", help="Branch to rebase (-b mode)")
    p_re.add_argument("-d", "--destination", dest="destinations", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (-d/--destination)")
    p_re.add_argument("-o", "--onto", dest="ontos", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (--onto synonym for -d)")
    p_re.add_argument("-A", "--insert-after", dest="insert_afters", action="append", default=None,
                      metavar="REVSETS", help="Insert after this revision")
    p_re.add_argument("-B", "--insert-before", dest="insert_befores", action="append", default=None,
                      metavar="REVSETS", help="Insert before this revision")

    # absorb
    p_ab = sub.add_parser("absorb", help="Move changes from a revision into ancestors")
    p_ab.add_argument("-f", "--from", dest="from_", default="@", metavar="REVSET",
                      help="Source revision to absorb from (default: @)")
    p_ab.add_argument("-t", "--into", "--to", dest="into", default=None, metavar="REVSETS",
                      help="Destination revisions to absorb into (default: mutable())")
    p_ab.add_argument("-i", "--interactive", action="store_true",
                      help="Interactively choose which parts to absorb")
    p_ab.add_argument("--tool", dest="tool", default=None, metavar="NAME",
                      help="Diff editor for interactive selection")
    p_ab.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to absorb (default: all)")

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
    p_hunk.add_argument("--json-schema", action="store_true", help="Dump JSON schema for LLM tool-calling and exit")
    hunk_sub = p_hunk.add_subparsers(dest="hunk_command")
    p_hunk_list = hunk_sub.add_parser("list", help="List hunks for a revision")
    p_hunk_list.add_argument("-r", "--revision", default="@", metavar="REVSET",
                             help="Revision to list hunks for (default: @)")
    p_hunk_list.add_argument("--format", choices=["json", "yaml", "text"], default="json",
                             help="Output format (default: json)")
    p_hunk_split = hunk_sub.add_parser("split", help="Split a revision with hunk/line spec")
    p_hunk_split.add_argument("-r", "--revision", default="@", metavar="REVSET",
                              help="Revision to split (default: @)")
    p_hunk_split.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                              help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_split.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                              help="Read spec from file (JSON/YAML)")
    p_hunk_split.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_split.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_split.add_argument("message", nargs="?", help="Commit message for first half (or '-' for stdin)")
    p_hunk_commit = hunk_sub.add_parser("commit", help="Commit selected hunks from working copy")
    p_hunk_commit.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_commit.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_commit.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_commit.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_commit.add_argument("message", nargs="?", help="Commit message (or '-' for stdin)")
    p_hunk_squash = hunk_sub.add_parser("squash", help="Squash selected hunks into parent")
    p_hunk_squash.add_argument("-r", "--revision", default="@", metavar="REVSET",
                               help="Revision to squash (default: @)")
    p_hunk_squash.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_squash.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_squash.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_schema = hunk_sub.add_parser("schema", help="Dump JSON schema for LLM tool-calling")
    p_hunk_schema.add_argument("--format", choices=["json", "yaml"], default="json",
                               help="Output format (default: json)")

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
        "diff": diff,
        "show": show,
        "file": lambda a: {"list": file_list, "show": file_show, "annotate": file_annotate}.get(
            a.file_command or "", _file_help
        )(a),
        "describe": describe,
        "new": new,
        "bookmark": bookmark,
        "squash": squash,
        "rebase": rebase,
        "absorb": absorb,
        "abandon": abandon,
        "duplicate": duplicate,
        "edit": edit,
        "commit": commit,
        "restore": restore,
        "split": split,
        "diffedit": diffedit,
        "resolve": resolve,
        "hunk": lambda a: hunk_schema(a) if getattr(a, "json_schema", False) else {
            "list": hunk_list,
            "split": hunk_split,
            "commit": hunk_commit,
            "squash": hunk_squash,
            "schema": hunk_schema,
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
    print("usage: pyjj bookmark {create,set,delete,forget,list,move,rename}", file=sys.stderr)
    return 2


def _op_help(args) -> int:
    print("usage: pyjj op {restore}", file=sys.stderr)
    return 2


def _file_help(args) -> int:
    print("usage: pyjj file {list,show,annotate}", file=sys.stderr)
    return 2


def _hunk_help(args) -> int:
    print("usage: pyjj hunk {list,split,commit,squash,schema}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
