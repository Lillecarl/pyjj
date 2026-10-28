from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_NAMES = ("workflow", "wf")


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser], argv: Sequence[str] | None = None) -> None:
    p = sub.add_parser(
        "workflow", aliases=["wf"],
        help="Run a workflow from a pyjj extension (pyjj-only)",
        description="Run a workflow: a `pyjj.Workflow` subclass in a file "
                    "the `pyjj.extensions` config key lists. With no name, "
                    "list them.")
    p.set_defaults(_handler="pyjj_cli.commands.workflow:workflow",
                   _workflow=None)
    # Finding the workflows means reading config and importing the
    # user's files. The parser is built on every run and every Tab, so
    # only a command line that names this command pays for that.
    if argv is None or not set(_NAMES) & set(argv):
        return
    nested = p.add_subparsers(dest="workflow_name", metavar="WORKFLOW")
    try:
        found = _discover(argv)
    except Exception as e:  # noqa: BLE001 -- reported when the command runs
        p.set_defaults(_workflow_error=getattr(e, "message", str(e)))
        return
    for name, cls in found.items():
        wp = nested.add_parser(name, help=cls.help, description=cls.help)
        cls().add_arguments(wp)
        wp.set_defaults(_workflow=name)


def _discover(argv: Sequence[str]):
    import pyjj

    from pyjj_cli.__main__ import _drop_ignored_global_flags, _hoist_global_options

    kept, _globals, config_args = _hoist_global_options(_drop_ignored_global_flags(list(argv)))
    repository = None
    for flag, value in zip(kept, kept[1:]):
        if flag in ("-R", "--repository"):
            repository = value
    for arg in kept:
        if arg.startswith("--repository="):
            repository = arg.partition("=")[2]
    settings = pyjj.UserSettings()
    try:
        ws = pyjj.Workspace.load(settings, repository or os.getcwd())
        settings = pyjj.UserSettings.for_repo(ws.repo_path, ws.workspace_root)
    except Exception:  # noqa: BLE001 -- user config alone still names extensions
        pass
    settings = settings.with_command_args(config_args)
    pyjj.extensions.load(settings)
    return pyjj.extensions.workflows()


def completion_argv() -> list[str] | None:
    """The words of the command line a shell is completing, if any."""
    line = os.environ.get("COMP_LINE")
    if not os.environ.get("_ARGCOMPLETE") or line is None:
        return None
    import shlex

    try:
        return shlex.split(line)[1:]
    except ValueError:
        return line.split()[1:]


def argv_for_parser(argv: Sequence[str] | None) -> list[str]:
    completing = completion_argv()
    if completing is not None:
        return completing
    return list(sys.argv[1:] if argv is None else argv)
