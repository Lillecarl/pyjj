"""`jj util`: infrequently used commands."""

from __future__ import annotations

import argparse
import sys

from .flags import Flag, add_flags


def _util_help(args: argparse.Namespace):
    print("usage: pyjj util {backend,completion,config-schema,diff,exec,gc,"
          "install-man-pages,markdown-help,snapshot}", file=sys.stderr)
    return 2


def _backend_help(args: argparse.Namespace):
    print("usage: pyjj util backend {name}", file=sys.stderr)
    return 2


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "util",
        help="Infrequently used commands such as for generating shell completions",
    )
    p.set_defaults(_handler="pyjj_cli.cli.util:_util_help")
    util_sub = p.add_subparsers(dest="util_command")

    p_gc = util_sub.add_parser("gc", help="Run backend-dependent garbage collection")
    p_gc.add_argument("--expire", default=None, metavar="EXPIRE",
                      help="Time threshold; only 'now' is accepted")
    p_gc.set_defaults(_handler="pyjj_cli.commands.util.gc:util_gc")

    p_snapshot = util_sub.add_parser(
        "snapshot", help="Snapshot the working copy if needed")
    p_snapshot.set_defaults(
        _handler="pyjj_cli.commands.util.snapshot:util_snapshot")

    p_exec = util_sub.add_parser("exec", help="Execute an external command via jj")
    p_exec.add_argument("command_name", nargs="?", default=None,
                        metavar="COMMAND", help="External command to execute")
    p_exec.add_argument("command_args", nargs=argparse.REMAINDER,
                        metavar="ARGS",
                        help="Arguments to pass to the external command")
    p_exec.set_defaults(_handler="pyjj_cli.commands.util.exec:util_exec")

    p_backend = util_sub.add_parser(
        "backend", help="Commands relating to the backend used in the current repo")
    p_backend.set_defaults(_handler="pyjj_cli.cli.util:_backend_help")
    backend_sub = p_backend.add_subparsers(dest="backend_command")
    p_backend_name = backend_sub.add_parser(
        "name", help="Print the name of the backend used in the current repo")
    p_backend_name.set_defaults(
        _handler="pyjj_cli.commands.util.backend:util_backend_name")

    p_diff = util_sub.add_parser("diff", help="Compare two files on disk")
    p_diff.add_argument("path1", metavar="PATH1", help="First path to compare")
    p_diff.add_argument("path2", metavar="PATH2", help="Second path to compare")
    add_flags(p_diff, {Flag.GIT, Flag.WHITESPACE, Flag.CONTEXT,
                       Flag.DIFF_TOOL})
    # Short listing formats: accepted but hidden, like jj's own
    # `mut_arg(hide(true))` -- `show_diff_bytes` omits the block for
    # all of them, so they only matter when combined with `--tool`.
    for _flag in ("--summary", "--stat", "--types", "--name-only"):
        p_diff.add_argument(_flag, action="store_true",
                            help=argparse.SUPPRESS)
    p_diff.set_defaults(_handler="pyjj_cli.commands.util.diff:util_diff")

    p_completion = util_sub.add_parser(
        "completion", help="Print a command-line-completion script")
    p_completion.add_argument(
        "shell", metavar="SHELL",
        choices=("bash", "elvish", "fish", "nushell", "power-shell", "zsh"),
        help="The shell to print the script for")
    p_completion.set_defaults(
        _handler="pyjj_cli.commands.util.completion:util_completion")

    p_schema = util_sub.add_parser(
        "config-schema", help="Print the JSON schema for the jj TOML config format")
    p_schema.set_defaults(
        _handler="pyjj_cli.commands.util.config_schema:util_config_schema")

    p_man = util_sub.add_parser(
        "install-man-pages", help="Install the manpages to the provided path")
    p_man.add_argument(
        "path", metavar="PATH",
        help="Where to install them; `man1` is appended")
    p_man.set_defaults(
        _handler="pyjj_cli.commands.util.man_pages:util_install_man_pages")

    p_markdown = util_sub.add_parser(
        "markdown-help", help="Print the CLI help for all subcommands in Markdown")
    p_markdown.set_defaults(
        _handler="pyjj_cli.commands.util.markdown_help:util_markdown_help")
