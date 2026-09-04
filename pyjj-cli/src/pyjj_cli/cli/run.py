"""Parser for `pyjj run`.

Mirrors `RunArgs` in `cli/src/commands/run.rs`. `ARGS` is
`argparse.REMAINDER` so `pyjj run -- cargo build --release` passes the
command's own flags through instead of trying to parse them.
"""
import argparse


def add_parsers(sub) -> None:
    p = sub.add_parser("run", help="Run a command across a set of revisions")
    p.add_argument("command", metavar="COMMAND",
                   help="Command to run across all selected revisions")
    p.add_argument("args", nargs=argparse.REMAINDER, metavar="ARGS",
                   help="Arguments to pass to the command")
    p.add_argument("-r", "--revision", "--revisions", dest="revisions",
                   action="append", default=None, metavar="REVSETS",
                   help="The revisions to change")
    # A no-op that exists so `jj run -x <cmd>` reads like `git rebase -x`.
    p.add_argument("-x", dest="exec", action="store_true",
                   help=argparse.SUPPRESS)
    p.add_argument("-j", "--jobs", type=int, default=None,
                   help="How many processes should run in parallel")
    p.add_argument("--root", action="store_true",
                   help="Run the command from the working-copy root in each "
                        "commit instead of from the subdirectory `pyjj run` "
                        "was invoked from")
    p.add_argument("--clean", action="store_true",
                   help="Delete each working copy before running the command")
    p.add_argument("--restore-descendants", dest="restore_descendants",
                   action="store_true",
                   help="Preserve the content (not the diff) when rebasing "
                        "descendants")
    p.set_defaults(_handler="pyjj_cli.commands.run:run")
