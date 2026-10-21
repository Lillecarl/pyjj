from __future__ import annotations

import argparse
import sys


def _stub(message: str):
    def _h(args: argparse.Namespace):
        print(f"Error: {message} is not yet supported", file=sys.stderr)
        return 2
    return _h


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_arrange = sub.add_parser("arrange", help="Interactively arrange the commit graph")
    p_arrange.add_argument("revisions", nargs="*", metavar="REVSETS",
                           help="The revisions to arrange (default: the "
                                "`revsets.arrange` setting)")
    p_arrange.add_argument("-r", "--revision", dest="revision_flags",
                           action="append", metavar="REVSETS",
                           help=argparse.SUPPRESS)
    p_arrange.set_defaults(_handler="pyjj_cli.commands.rewrite.arrange:arrange")
    p_gerrit = sub.add_parser("gerrit", help="Interact with Gerrit Code Review")
    p_gerrit.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_gerrit")
    p_help = sub.add_parser("help", help="Print this message or the help of the given subcommand(s)")
    p_help.add_argument("topic", nargs="*", metavar="COMMAND",
                        help="Command to describe")
    p_help.set_defaults(_handler="pyjj_cli.cli.stubs:help_command")


def _stub_gerrit(args: argparse.Namespace):
    import sys
    print("Error: gerrit is not yet supported", file=sys.stderr)
    return 2


def help_command(args: argparse.Namespace):
    """`jj help [COMMAND]`: print the top-level help, or one command's."""
    from pyjj_cli.__main__ import build_parser

    parser = build_parser()
    for name in getattr(args, "topic", None) or []:
        parser = _subparser(parser, name)
        if parser is None:
            import sys
            print(f"Error: Unknown command `{name}`", file=sys.stderr)
            return 2
    parser.print_help()
    return 0


def _subparser(parser: argparse.ArgumentParser, name):
    for action in parser._actions:
        mapping = getattr(action, "_name_parser_map", None)
        if mapping and name in mapping:
            return mapping[name]
    return None
