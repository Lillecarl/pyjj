"""`jj debug`: thin over `pyjj_bindings.debug_*`, which render jj-lib's
internals with the same `Debug` formatting jj prints.

jj loads some of these without snapshotting (`index`, `reindex`,
`object`, `working-copy`), so a broken working copy or index can still
be inspected; those use `_no_snapshot` here as well.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import pyjj_bindings

import pyjj

from . import common
from .common import (
    _resolve_one,
    _resolve_operation,
    _workspace_path,
    command,
    read_repo,
    settings_for,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

_T = TypeVar("_T")


def _no_snapshot(args: argparse.Namespace):
    settings = settings_for(args)
    return settings, pyjj.Workspace.load(settings, _workspace_path(args))


def _usage(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


@command
def debug_copy_detection(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, _ws, repo):
        commit = _resolve_one(repo, settings, args.revision)
        sys.stdout.write(pyjj_bindings.debug_copy_detection(repo, commit))
    return 0


@command
def debug_fileset(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, ws, _repo):
        sys.stdout.write(pyjj_bindings.debug_fileset(
            settings, ws.workspace_root, os.getcwd(), args.path))
    return 0


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_index(args: argparse.Namespace) -> int:
    _settings, ws = _no_snapshot(args)
    sys.stdout.write(pyjj_bindings.debug_index(ws))
    return 0


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_reindex(args: argparse.Namespace) -> int:
    _settings, ws = _no_snapshot(args)
    count = pyjj_bindings.debug_reindex(ws)
    print(f"Finished indexing {count} commits.", file=sys.stderr)
    return 0


@command
def debug_index_changed_paths(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, repo):
        indexed = pyjj_bindings.debug_index_changed_paths(ws, repo, args.limit)
    if indexed is None:
        print("No commits indexed.", file=sys.stderr)
    else:
        print(f"Finished indexing {indexed} commits.", file=sys.stderr)
    return 0


@command(catch=(pyjj.WorkspaceInitError,))
def debug_init_simple(args: argparse.Namespace) -> int:
    if common._IGNORE_WORKING_COPY:
        return _usage("--ignore-working-copy is not respected")
    if getattr(args, "at_operation", None):
        return _usage("--at-op is not respected")
    destination = Path(os.getcwd(), args.destination)
    try:
        destination.mkdir(exist_ok=True)
        destination = destination.resolve()
    except OSError as e:
        print("Error: Failed to create workspace", file=sys.stderr)
        print(f"Caused by: {e.strerror}", file=sys.stderr)
        return 1
    pyjj_bindings.debug_init_simple(common.apply_config_args(pyjj.UserSettings()),
                                    str(destination))
    print(f'Initialized repo in "{os.path.relpath(destination)}"', file=sys.stderr)
    return 0


@command
def debug_local_working_copy(args: argparse.Namespace) -> int:
    with read_repo(args) as (_settings, ws, _repo):
        sys.stdout.write(pyjj_bindings.debug_local_working_copy(ws))
    return 0


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_working_copy(args: argparse.Namespace) -> int:
    _settings, ws = _no_snapshot(args)
    sys.stdout.write(pyjj_bindings.debug_working_copy(ws))
    return 0


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_object_commit(args: argparse.Namespace) -> int:
    _settings, ws = _no_snapshot(args)
    sys.stdout.write(pyjj_bindings.debug_object_commit(ws, args.id))
    return 0


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_object_operation(args: argparse.Namespace) -> int:
    _settings, ws = _no_snapshot(args)
    sys.stdout.write(pyjj_bindings.debug_object_operation(ws, args.id))
    return 0


def _object_target(args: argparse.Namespace, required: bool):
    """`(ws, id, commit)` for `object file/symlink/tree`: an id, or the
    commit `--revision` names. jj's clap group allows one of the two."""
    if args.id is not None and args.revision is not None:
        raise _UsageError("the argument '[ID]' cannot be used with "
                          "'--revision <REVISION>'")
    if required and args.id is None and args.revision is None:
        raise _UsageError("the following required arguments were not "
                          "provided:\n  <ID|--revision <REVISION>>")
    settings, ws = _no_snapshot(args)
    commit = None
    if args.revision is not None:
        commit = _resolve_one(ws.load_at_head(), settings, args.revision)
    return ws, args.id, commit


class _UsageError(Exception):
    pass


def _object(
    fn: Callable[..., _T], required: bool, name: str, write: Callable[[_T], object],
):
    @command(catch=(pyjj.WorkspaceLoadError,))
    def run(args: argparse.Namespace) -> int:
        try:
            ws, id_, commit = _object_target(args, required)
        except _UsageError as e:
            return _usage(str(e))
        write(fn(ws, getattr(args, name), id=id_, commit=commit))
        return 0
    return run


debug_object_file = _object(pyjj_bindings.debug_object_file, True, "path",
                            lambda data: sys.stdout.buffer.write(data))
debug_object_symlink = _object(pyjj_bindings.debug_object_symlink, False,
                               "path", lambda text: sys.stdout.write(text))
debug_object_tree = _object(pyjj_bindings.debug_object_tree, True, "dir",
                            lambda text: sys.stdout.write(text))


@command(catch=(pyjj.WorkspaceLoadError,))
def debug_object_view(args: argparse.Namespace) -> int:
    if args.id is not None and args.op is not None:
        return _usage("the argument '[ID]' cannot be used with '--op <OP>'")
    if args.id is None and args.op is None:
        return _usage("the following required arguments were not "
                      "provided:\n  <ID|--op <OP>>")
    _settings, ws = _no_snapshot(args)
    op = (_resolve_operation(ws.load_at_head(), args.op)
          if args.op is not None else None)
    sys.stdout.write(pyjj_bindings.debug_object_view(ws, id=args.id, op=op))
    return 0


@command
def debug_revset(args: argparse.Namespace) -> int:
    with read_repo(args) as (settings, _ws, repo):
        sys.stdout.write(pyjj_bindings.debug_revset(
            repo, settings, args.revision, no_resolve=args.no_resolve,
            no_optimize=args.no_optimize))
    return 0


@command
def debug_snapshot(args: argparse.Namespace) -> int:
    print("Warning: `jj debug snapshot` is deprecated; use `jj util snapshot` "
          "instead.", file=sys.stderr)
    with read_repo(args):
        pass
    return 0


@command
def debug_stacked_table(args: argparse.Namespace) -> int:
    sys.stdout.write(pyjj_bindings.debug_stacked_table(args.dir, args.key_size))
    return 0


def debug_template(args: argparse.Namespace) -> int:
    """pyjj's templates are Jinja, so this prints the Jinja parse tree in
    the layout jj's `{:#?}` gives its own template AST."""
    from jinja2 import TemplateSyntaxError
    from jinja2.sandbox import SandboxedEnvironment

    try:
        tree = SandboxedEnvironment().parse(args.template)
    except TemplateSyntaxError as e:
        print(f"Error: Failed to parse template: {e}", file=sys.stderr)
        return 1
    print(_pretty(tree))
    return 0


def _pretty(value: object, indent: int = 0) -> str:
    from jinja2 import nodes

    pad = "    " * (indent + 1)
    if isinstance(value, nodes.Node):
        fields = [f"{pad}{name}: {_pretty(field, indent + 1)},"
                  for name, field in value.iter_fields()]
        if not fields:
            return type(value).__name__
        return "\n".join([f"{type(value).__name__} {{", *fields,
                          "    " * indent + "}"])
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{pad}{_pretty(item, indent + 1)}," for item in value]
        return "\n".join(["[", *items, "    " * indent + "]"])
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return repr(value)


@command
def debug_tree(args: argparse.Namespace) -> int:
    if args.id is not None and args.revision is not None:
        return _usage("the argument '--id <ID>' cannot be used with "
                      "'--revision <REVSET>'")
    if args.dir is not None and args.id is None:
        return _usage("the following required arguments were not "
                      "provided:\n  --id <ID>")
    with read_repo(args) as (settings, _ws, repo):
        commit = (None if args.id is not None
                  else _resolve_one(repo, settings, args.revision or "@"))
        sys.stdout.write(pyjj_bindings.debug_tree(
            repo, settings, os.getcwd(), list(args.paths), commit=commit,
            id=args.id, dir=args.dir))
    return 0


def _watchman(subcommand: str):
    @command
    def run(args: argparse.Namespace) -> int:
        with read_repo(args) as (settings, ws, _repo):
            out, status, error = pyjj_bindings.debug_watchman(
                ws, settings, subcommand)
        sys.stdout.write(out)
        sys.stderr.write(status)
        if error is not None:
            message, code = error
            print(message, file=sys.stderr)
            return code
        return 0
    return run


debug_watchman_status = _watchman("status")
debug_watchman_query_clock = _watchman("query-clock")
debug_watchman_query_changed_files = _watchman("query-changed-files")
debug_watchman_reset_clock = _watchman("reset-clock")
