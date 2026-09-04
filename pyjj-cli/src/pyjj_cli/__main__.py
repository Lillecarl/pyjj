#!/usr/bin/env python3
"""pyjj-cli — Python CLI for Jujutsu VCS, backed by the pyjj Rust bindings.

Command and argument shapes mirror the real `jj` CLI so that the parity
suite (pyjj/tests/parity) can run the same argv through both tools.

This module is deliberately thin: it only builds the argparse tree via
`pyjj_cli.cli.*` (each small, no heavy imports) and lazy-loads the
actual handler via `importlib` only after parsing, so `--help` and
`<TAB>` completion stay fast.
"""

import argparse
import importlib
import sys

import argcomplete


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyjj",
        description="Jujutsu VCS — Python CLI (pyjj bindings)",
    )
    parser.add_argument(
        "-R", "--repository", dest="repository", default=None,
        help="Path to the workspace to operate on (default: search up from "
             "the current directory)",
    )
    sub = parser.add_subparsers(dest="command")

    # Each cli.* module registers its own top-level command(s) onto `sub`.
    # Imported here (not at top-level) so `import pyjj_cli.__main__` doesn't
    # pull them until `build_parser()` is actually called — and none of them
    # import `pyjj`/`pyjj.hunk`/`pydantic` themselves.
    from pyjj_cli.cli import bisect, bookmark, config, describe, file, git, history, hunk, operation, rewrite, run, sparse, stubs, tag, templates, util, workspace

    git.add_parsers(sub)
    history.add_parsers(sub)
    file.add_parsers(sub)
    describe.add_parsers(sub)
    bookmark.add_parsers(sub)
    rewrite.add_parsers(sub)
    hunk.add_parsers(sub)
    sparse.add_parsers(sub)
    workspace.add_parsers(sub)
    tag.add_parsers(sub)
    config.add_parsers(sub)
    operation.add_parsers(sub)
    templates.add_parsers(sub)
    bisect.add_parsers(sub)
    util.add_parsers(sub)
    run.add_parsers(sub)
    stubs.add_parsers(sub)

    return parser


# jj takes its global options anywhere on the command line, before or
# after the subcommand. These three change only what gets printed, never
# what gets written, so pyjj accepts them and does nothing with them --
# a script that passes `--no-pager` must not die on a usage dump.
# `--config` and `--ignore-immutable` are still deliberately absent:
# silently ignoring one of those would make pyjj quietly disagree with
# jj. `--at-operation`, `--ignore-working-copy` and `--color` are
# honoured, and handled below rather than here, because they change what
# happens.
_IGNORED_GLOBAL_FLAGS = {"--no-pager", "--quiet", "--debug"}
_IGNORED_GLOBAL_OPTIONS: set[str] = set()

# Globals that change behaviour. argparse only accepts top-level options
# before the subcommand, so these are lifted out of `argv` wherever they
# appear and applied to the parsed namespace afterwards.
_HOISTED_GLOBAL_FLAGS = {"--ignore-working-copy": "ignore_working_copy"}
_HOISTED_GLOBAL_OPTIONS = {"--at-operation": "at_operation",
                           "--at-op": "at_operation",
                           "--color": "color"}

# What `--color` accepts, in jj's order.
_COLOR_CHOICES = ("always", "never", "debug", "auto")


# The global options above never reach `argparse`, so a walk of the
# parser tree cannot see them. Publish them for `cli_surface`, which
# measures pyjj-cli's argument surface against jj's and would otherwise
# report every one of them as missing.
GLOBAL_FLAGS_OUTSIDE_ARGPARSE = frozenset(
    _IGNORED_GLOBAL_FLAGS
    | _IGNORED_GLOBAL_OPTIONS
    | set(_HOISTED_GLOBAL_FLAGS)
    | set(_HOISTED_GLOBAL_OPTIONS)
)


def _hoist_global_options(argv):
    """Pull the behaviour-changing globals out of `argv`.

    Returns the remaining argv and a dict of what was found. jj takes
    these anywhere on the command line; argparse would only see them in
    front of the subcommand.
    """
    kept = []
    found = {}
    pending = None
    for arg in argv:
        if pending is not None:
            found[pending] = arg
            pending = None
            continue
        if arg in _HOISTED_GLOBAL_FLAGS:
            found[_HOISTED_GLOBAL_FLAGS[arg]] = True
            continue
        if arg in _HOISTED_GLOBAL_OPTIONS:
            pending = _HOISTED_GLOBAL_OPTIONS[arg]
            continue
        name, sep, value = arg.partition("=")
        if sep and name in _HOISTED_GLOBAL_OPTIONS:
            found[_HOISTED_GLOBAL_OPTIONS[name]] = value
            continue
        kept.append(arg)
    if pending is not None:
        # jj's clap says "a value is required"; dropping it silently
        # would run the command against the wrong operation.
        raise SystemExit(
            f"Error: a value is required for '--{pending.replace('_', '-')}'"
        )
    return kept, found


def _drop_ignored_global_flags(argv):
    """Strip display-only global options from anywhere in `argv`."""
    kept = []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg in _IGNORED_GLOBAL_FLAGS:
            continue
        if arg in _IGNORED_GLOBAL_OPTIONS:
            # Its value follows, unless it was given as `--color=always`.
            skip = i + 1 < len(argv)
            continue
        if any(arg.startswith(f"{name}=") for name in _IGNORED_GLOBAL_OPTIONS):
            continue
        kept.append(arg)
    return kept


def _load_handler(dotted: str):
    mod_name, func_name = dotted.rsplit(":", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, func_name)


def main(argv=None) -> int:
    parser = build_parser()
    # Completion runs the CLI itself on every <TAB>; keep everything heavy
    # out of that path — handlers are not imported yet.
    argcomplete.autocomplete(parser)
    raw = sys.argv[1:] if argv is None else argv
    # Kept before the globals are stripped: this is the command line the
    # operation log records, and it should read as what was typed.
    invocation = list(raw)
    raw, globals_ = _hoist_global_options(_drop_ignored_global_flags(raw))
    args = parser.parse_args(raw)
    args.at_operation = globals_.get("at_operation")
    # Loading the repo at a past operation implies not touching the
    # working copy, the same way jj documents it.
    args.ignore_working_copy = bool(
        globals_.get("ignore_working_copy") or args.at_operation
    )
    # Imported here, not at module scope: it pulls in `pyjj`, and this
    # line sits after `autocomplete()`, which exits during completion.
    from pyjj_cli.commands import common
    common.set_ignore_working_copy(args.ignore_working_copy)
    common.set_operation_args(invocation)
    colour = globals_.get("color")
    if colour is not None and colour not in _COLOR_CHOICES:
        # jj's clap rejects anything else, and naming the accepted
        # values is what it prints.
        print(f"Error: invalid value '{colour}' for '--color <WHEN>'\n"
              f"  [possible values: {', '.join(_COLOR_CHOICES)}]",
              file=sys.stderr)
        return 2
    common.set_color_choice(colour)
    if args.command is None:
        parser.print_help()
        return 1

    # Leaf parser set `_handler` (dotted "module:func"). Fall back to help
    # if a subcommand was omitted (e.g. `pyjj git` with no subcommand).
    handler_ref = getattr(args, "_handler", None)
    if handler_ref is None:
        parser.print_help()
        return 2

    handler = _load_handler(handler_ref)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
