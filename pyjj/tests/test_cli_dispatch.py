"""Every registered command must dispatch to a function that exists.

`pyjj-cli` names its handlers as `"module:function"` strings so that
`--help` and shell completion stay fast -- nothing heavy is imported
while the parser is built. The cost is that a typo in one of those
strings is invisible until someone runs that exact subcommand, and it
then surfaces as an AttributeError traceback rather than an error
message. Three bookmark subcommands shipped that way.
"""

import argparse
import importlib
import pkgutil

import pytest

import pyjj_cli.cli
from pyjj_cli.__main__ import build_parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyjj")
    sub = parser.add_subparsers(dest="command")
    for module in sorted(pkgutil.iter_modules(pyjj_cli.cli.__path__)):
        registrar = importlib.import_module(f"pyjj_cli.cli.{module.name}")
        if hasattr(registrar, "add_parsers"):
            registrar.add_parsers(sub)
    return parser


def _handlers(parser, prefix=""):
    """Every (command path, handler reference) the parser can dispatch."""
    for action in parser._actions:
        if not hasattr(action, "_name_parser_map"):
            continue
        seen = set()
        for name, subparser in action._name_parser_map.items():
            if id(subparser) in seen:
                continue
            seen.add(id(subparser))
            path = f"{prefix}{name}"
            reference = subparser.get_default("_handler")
            if reference:
                yield path, reference
            yield from _handlers(subparser, f"{path} ")


HANDLERS = sorted(set(_handlers(_parser())))


def test_the_parser_registers_handlers():
    assert len(HANDLERS) > 50, HANDLERS


@pytest.mark.parametrize("path,reference", HANDLERS, ids=lambda v: v)
def test_handler_resolves(path, reference):
    module_name, _, function_name = reference.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, function_name, None)), (
        f"`pyjj {path}` points at {reference}, which does not exist"
    )


@pytest.mark.parametrize("alias,canonical", [
    ("st", "status"),
    ("ci", "commit"),
    ("b", "bookmark"),
    ("evolution-log", "evolog"),
])
def test_default_command_aliases_dispatch_like_their_canonical(alias, canonical):
    """jj's `[default alias: ...]` spellings work, not just the long names.

    Only `desc` had one; `st`, `ci`, `b` and `evolution-log` all errored
    with `invalid choice`. An alias shares its parser, so the handler
    must be identical -- argparse records the spelling used, which
    nothing here reads.
    """
    parser = build_parser()
    via_alias = parser.parse_args([alias])
    via_canonical = parser.parse_args([canonical])
    assert getattr(via_alias, "_handler") == getattr(via_canonical, "_handler")


@pytest.mark.covers("arrange", "-r")
def test_arrange_parses_r_flag():
    """`arrange` is a stub that refuses everything, but `-r` is argv jj
    accepts, so it must parse rather than fail with `invalid choice`.
    Parsing is the whole of this flag's surface until arrange exists.
    """
    args = build_parser().parse_args(["arrange", "-r", "@"])
    assert args.revision_flags == ["@"]
