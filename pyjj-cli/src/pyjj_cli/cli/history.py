import argparse

from .flags import Flag, add_flags, add_revision_flag, add_filesets_flag


def add_parsers(sub) -> None:
    p_status = sub.add_parser("status", help="Show working copy status")
    p_status.set_defaults(_handler="pyjj_cli.commands.history.status:status")

    p_log = sub.add_parser("log", help="Show commit history")
    add_flags(p_log, {Flag.REVISIONS, Flag.LIMIT, Flag.NO_GRAPH, Flag.TEMPLATE, Flag.PATCH})
    # log's filesets is suppressed (not shown in help) — keep manual for that nuance
    p_log.add_argument("filesets", nargs="*", metavar="FILESETS", help=argparse.SUPPRESS)
    p_log.set_defaults(_handler="pyjj_cli.commands.history.log:log")

    p_diff = sub.add_parser("diff", help="Compare file contents between two revisions")
    add_flags(p_diff, {Flag.REVISIONS, Flag.FROM, Flag.TO, Flag.SUMMARY, Flag.STAT, Flag.NAME_ONLY, Flag.GIT, Flag.TEMPLATE, Flag.FILESETS})
    p_diff.set_defaults(_handler="pyjj_cli.commands.history.diff:diff")

    p_show = sub.add_parser("show", help="Show revision metadata and diff")
    p_show.add_argument("revisions", nargs="*", metavar="REVSETS", help="Revisions to show (default: @)")
    add_flags(p_show, {Flag.TEMPLATE, Flag.SUMMARY, Flag.STAT, Flag.NAME_ONLY, Flag.GIT, Flag.NO_PATCH})
    p_show.set_defaults(_handler="pyjj_cli.commands.history.show:show")
