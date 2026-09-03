import argparse


def _bisect_help(args):
    import sys
    print("usage: pyjj bisect run --range REVSETS [COMMAND [ARGS...]]", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_bisect = sub.add_parser("bisect", help="Find a bad revision by bisection")
    p_bisect.set_defaults(_handler="pyjj_cli.cli.bisect:_bisect_help")
    bisect_sub = p_bisect.add_subparsers(dest="bisect_command")

    p_run = bisect_sub.add_parser(
        "run", help="Run a given command to find the first bad revision"
    )
    p_run.add_argument("-r", "--range", dest="range", action="append", metavar="REVSETS",
                       required=True,
                       help="Range of revisions to bisect (can be repeated)")
    p_run.add_argument("--find-good", dest="find_good", action="store_true",
                       help="Find the first good revision instead")
    # `dest` must not be "command": the top-level subparser already owns
    # that name, and reusing it overwrites the dispatch key.
    p_run.add_argument("cmd", nargs="?", metavar="COMMAND",
                       help="Command to run to determine the status of a revision")
    p_run.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="ARGS",
                       help="Arguments to pass to the command")
    p_run.set_defaults(_handler="pyjj_cli.commands.bisect.run:bisect_run")
