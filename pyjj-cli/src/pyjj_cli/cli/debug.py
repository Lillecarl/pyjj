"""`jj debug`: low-level commands not intended for users."""

from __future__ import annotations

import argparse
import sys

_H = "pyjj_cli.commands.debug"


def _debug_help(args: argparse.Namespace):
    print("usage: pyjj debug {copy-detection,fileset,index,index-changed-paths,"
          "init-simple,local-working-copy,object,reindex,revset,stacked-table,"
          "template,tree,watchman,working-copy}", file=sys.stderr)
    return 2


def _object_help(args: argparse.Namespace):
    print("usage: pyjj debug object {commit,file,operation,symlink,tree,view}",
          file=sys.stderr)
    return 2


def _watchman_help(args: argparse.Namespace):
    print("usage: pyjj debug watchman "
          "{status,query-clock,query-changed-files,reset-clock}", file=sys.stderr)
    return 2


def _object_target(p: argparse.ArgumentParser, name: str, metavar: str) -> None:
    p.add_argument(name, metavar=metavar)
    p.add_argument("id", nargs="?", metavar="ID")
    p.add_argument("-r", "--revision", metavar="REVSET")


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    # Hidden, as clap hides it in jj: off `--help` and `markdown-help`.
    p = sub.add_parser("debug", help=argparse.SUPPRESS,
                       description="Low-level commands not intended for users")
    p.set_defaults(_handler=f"{__name__}:_debug_help")
    debug = p.add_subparsers(dest="debug_command")

    def add(name: str, handler: str, help_: str | None = None) -> argparse.ArgumentParser:
        child = debug.add_parser(name, help=help_)
        child.set_defaults(_handler=f"{_H}:{handler}")
        return child

    c = add("copy-detection", "debug_copy_detection",
            "Show information about file copies detected")
    c.add_argument("revision", nargs="?", default="@", metavar="REVSET",
                   help="Show file copies detected in changed files in this "
                        "revision, compared to its parent(s)")

    c = add("fileset", "debug_fileset", "Parse fileset expression")
    c.add_argument("path", metavar="PATH")

    add("index", "debug_index", "Show commit index stats")

    c = add("index-changed-paths", "debug_index_changed_paths",
            "Build changed-path index")
    c.add_argument("-n", "--limit", type=int, default=2**32 - 1,
                   help="Limit number of revisions to index")

    c = add("init-simple", "debug_init_simple",
            "Create a new repo in the given directory using the "
            "proof-of-concept simple backend")
    c.add_argument("destination", nargs="?", default=".",
                   metavar="DESTINATION", help="The destination directory")

    add("local-working-copy", "debug_local_working_copy",
        "Show information about the local working copy state")

    c = debug.add_parser("object",
                         help="Show information about an operation and its view")
    c.set_defaults(_handler=f"{__name__}:_object_help")
    objects = c.add_subparsers(dest="object_command")
    o = objects.add_parser("commit")
    o.add_argument("id", metavar="ID")
    o.set_defaults(_handler=f"{_H}:debug_object_commit")
    o = objects.add_parser("file")
    _object_target(o, "path", "PATH")
    o.set_defaults(_handler=f"{_H}:debug_object_file")
    o = objects.add_parser("operation")
    o.add_argument("id", metavar="ID")
    o.set_defaults(_handler=f"{_H}:debug_object_operation")
    o = objects.add_parser("symlink")
    _object_target(o, "path", "PATH")
    o.set_defaults(_handler=f"{_H}:debug_object_symlink")
    o = objects.add_parser("tree")
    _object_target(o, "dir", "DIR")
    o.set_defaults(_handler=f"{_H}:debug_object_tree")
    o = objects.add_parser("view")
    o.add_argument("id", nargs="?", metavar="ID")
    o.add_argument("--op", metavar="OP")
    o.set_defaults(_handler=f"{_H}:debug_object_view")

    add("reindex", "debug_reindex", "Rebuild commit index")

    c = add("revset", "debug_revset", "Evaluate revset to full commit IDs")
    c.add_argument("revision", metavar="REVISION")
    c.add_argument("--no-resolve", action="store_true",
                   help="Do not resolve and evaluate expression")
    c.add_argument("--no-optimize", action="store_true",
                   help="Do not rewrite expression to optimized form")

    snapshot = debug.add_parser("snapshot", help=argparse.SUPPRESS)
    snapshot.set_defaults(_handler=f"{_H}:debug_snapshot")

    c = add("stacked-table", "debug_stacked_table", "Show stats of stacked table")
    c.add_argument("dir", metavar="DIR", help="Path to table store directory")
    c.add_argument("-n", "--key-size", type=int, required=True,
                   help="Key size in bytes")

    c = add("template", "debug_template", "Parse a template")
    c.add_argument("template", metavar="TEMPLATE")

    c = add("tree", "debug_tree", "List the recursive entries of a tree")
    c.add_argument("-r", "--revision", metavar="REVSET")
    c.add_argument("--id")
    c.add_argument("--dir")
    c.add_argument("paths", nargs="*", metavar="FILESETS")

    c = debug.add_parser("watchman")
    c.set_defaults(_handler=f"{__name__}:_watchman_help")
    watchman = c.add_subparsers(dest="watchman_command")
    w = watchman.add_parser(
        "status", help="Check whether `watchman` is enabled and whether it's "
                       "correctly installed")
    w.set_defaults(_handler=f"{_H}:debug_watchman_status")
    for name, handler in (("query-clock", "debug_watchman_query_clock"),
                          ("query-changed-files",
                           "debug_watchman_query_changed_files"),
                          ("reset-clock", "debug_watchman_reset_clock")):
        watchman.add_parser(name).set_defaults(_handler=f"{_H}:{handler}")

    add("working-copy", "debug_working_copy",
        "Show information about the working copy state")
