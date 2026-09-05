import argparse

from .flags import Flag, add_flags


def add_parsers(sub) -> None:
    p_status = sub.add_parser("status", help="Show working copy status")
    p_status.set_defaults(_handler="pyjj_cli.commands.history.status:status")

    p_log = sub.add_parser("log", help="Show commit history")
    add_flags(p_log, [Flag.REVISIONS, Flag.LIMIT, Flag.NO_GRAPH,
                      Flag.TEMPLATE, Flag.PATCH, Flag.SUMMARY, Flag.STAT,
                      Flag.NAME_ONLY, Flag.TYPES, Flag.GIT,
                      Flag.WHITESPACE_LONG, Flag.CONTEXT])
    p_log.add_argument("--reversed", action="store_true",
                       help="Show oldest commits first")
    p_log.add_argument("--count", action="store_true",
                       help="Print the number of commits instead of showing them")
    # log's filesets is suppressed (not shown in help) — keep manual for that nuance
    p_log.add_argument("filesets", nargs="*", metavar="FILESETS", help=argparse.SUPPRESS)
    p_log.set_defaults(_handler="pyjj_cli.commands.history.log:log")

    p_diff = sub.add_parser("diff", help="Compare file contents between two revisions")
    add_flags(p_diff, [Flag.REVISIONS, Flag.FROM, Flag.TO, Flag.SUMMARY, Flag.STAT, Flag.NAME_ONLY, Flag.TYPES, Flag.GIT, Flag.WHITESPACE, Flag.CONTEXT, Flag.TEMPLATE, Flag.FILESETS])
    p_diff.set_defaults(_handler="pyjj_cli.commands.history.diff:diff")

    p_show = sub.add_parser("show", help="Show revision metadata and diff")
    p_show.add_argument("revisions", nargs="*", metavar="REVSETS", help="Revisions to show (default: @)")
    # jj takes show's revisions positionally and also accepts -r for
    # them. The two cannot share a dest: an empty `nargs="*"` positional
    # assigns its empty list last and drops whatever `-r` appended, so
    # `-r` gets its own name and `show` joins the two.
    p_show.add_argument("-r", "--revision", dest="revision_flags",
                        action="append", metavar="REVSETS",
                        help="Revisions to show")
    add_flags(p_show, [Flag.TEMPLATE, Flag.SUMMARY, Flag.STAT, Flag.NAME_ONLY, Flag.TYPES, Flag.GIT, Flag.WHITESPACE, Flag.CONTEXT, Flag.NO_PATCH])
    p_show.set_defaults(_handler="pyjj_cli.commands.history.show:show")
