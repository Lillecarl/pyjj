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
        "-R", "--repository", dest="repository", default=".",
        help="Path to the workspace to operate on (default: .)",
    )
    sub = parser.add_subparsers(dest="command")

    # Each cli.* module registers its own top-level command(s) onto `sub`.
    # Imported here (not at top-level) so `import pyjj_cli.__main__` doesn't
    # pull them until `build_parser()` is actually called — and none of them
    # import `pyjj`/`pyjj.hunk`/`pydantic` themselves.
    from pyjj_cli.cli import bisect, bookmark, config, describe, file, git, history, hunk, operation, rewrite, sparse, stubs, tag, templates, workspace

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
    stubs.add_parsers(sub)

    return parser


# jj takes its global options anywhere on the command line, before or
# after the subcommand. These four change only what gets printed, never
# what gets written, so pyjj accepts them and does nothing with them --
# a script that passes `--no-pager` must not die on a usage dump.
# The ones that DO change behaviour (`--at-operation`,
# `--ignore-working-copy`, `--config`, `--ignore-immutable`) are
# deliberately absent: silently ignoring one of those would make pyjj
# quietly disagree with jj.
_IGNORED_GLOBAL_FLAGS = {"--no-pager", "--quiet", "--debug"}
_IGNORED_GLOBAL_OPTIONS = {"--color"}


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
    args = parser.parse_args(
        _drop_ignored_global_flags(sys.argv[1:] if argv is None else argv)
    )
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
