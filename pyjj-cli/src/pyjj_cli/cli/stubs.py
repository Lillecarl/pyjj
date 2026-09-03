import argparse
import sys


def _stub(message: str):
    def _h(args):
        print(f"Error: {message} is not yet supported", file=sys.stderr)
        return 2
    return _h


def add_parsers(sub) -> None:
    p_arrange = sub.add_parser("arrange", help="Interactively arrange the commit graph")
    p_arrange.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_arrange")
    p_gerrit = sub.add_parser("gerrit", help="Interact with Gerrit Code Review")
    p_gerrit.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_gerrit")
    p_help = sub.add_parser("help", help="Print this message or the help of the given subcommand(s)")
    p_help.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_help")
    p_run = sub.add_parser("run", help="Run a command across a set of revisions")
    p_run.add_argument("-r", "--revision", dest="revisions", default=None, help=argparse.SUPPRESS)
    p_run.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_run")
    p_util = sub.add_parser("util", help="Infrequently used commands such as for generating shell completions")
    p_util.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_util")
    p_bench = sub.add_parser("bench", help="Benchmarking commands")
    p_bench.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_bench")
    p_debug = sub.add_parser("debug", help="Low-level commands not intended for users")
    p_debug.set_defaults(_handler="pyjj_cli.cli.stubs:_stub_debug")


def _stub_arrange(args):
    import sys
    print("Error: arrange is not yet supported", file=sys.stderr)
    return 2


def _stub_gerrit(args):
    import sys
    print("Error: gerrit is not yet supported", file=sys.stderr)
    return 2


def _stub_help(args):
    import sys
    print("Error: help is not yet supported", file=sys.stderr)
    return 2


def _stub_run(args):
    import sys
    print("Error: run is not yet supported", file=sys.stderr)
    return 2


def _stub_util(args):
    import sys
    print("Error: util is not yet supported", file=sys.stderr)
    return 2


def _stub_bench(args):
    import sys
    print("Error: bench is not yet supported", file=sys.stderr)
    return 2


def _stub_debug(args):
    import sys
    print("Error: debug is not yet supported", file=sys.stderr)
    return 2
