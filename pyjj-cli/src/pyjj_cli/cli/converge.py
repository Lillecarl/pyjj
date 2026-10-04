"""Parser for `pyjj converge`.

Mirrors `ConvergeArgs` in `cli/src/commands/converge.rs`: repeatable
`-r/--revision` (with jj's `--revisions` alias spelling), plus
`--no-interactive`. jj also takes a hidden `--interactive` no-op flag
(paired against `--no-interactive`); it is accepted and ignored here,
where the auto-solve path runs either way.
"""
import argparse


def add_parsers(sub) -> None:
    p = sub.add_parser("converge", help="Converge divergent changes")
    p.add_argument("-r", "--revision", "--revisions", dest="revisions",
                   action="append", default=None, metavar="REVSETS",
                   help="The search space to look for divergent revisions")
    p.add_argument("--no-interactive", dest="no_interactive",
                   action="store_true",
                   help="Do not prompt for help resolving divergence")
    p.add_argument("-i", "--interactive", dest="interactive",
                   action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(_handler="pyjj_cli.commands.converge:converge")
