import argparse


def add_parsers(sub) -> None:
    p_status = sub.add_parser("status", help="Show working copy status")
    p_status.set_defaults(_handler="pyjj_cli.commands:status")

    p_log = sub.add_parser("log", help="Show commit history")
    p_log.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                       help="Which revisions to show (revset)")
    p_log.add_argument("-n", "--limit", type=int, default=10, metavar="LIMIT",
                       help="Max commits to show (default: 10)")
    p_log.add_argument("-G", "--no-graph", action="store_true", help="Don't show the graph")
    p_log.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                       help=argparse.SUPPRESS)
    p_log.add_argument("-p", "--patch", action="store_true", help="Show patch")
    p_log.add_argument("filesets", nargs="*", metavar="FILESETS", help=argparse.SUPPRESS)
    p_log.set_defaults(_handler="pyjj_cli.commands:log")

    p_diff = sub.add_parser("diff", help="Compare file contents between two revisions")
    p_diff.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                        help="Show changes in these revisions")
    p_diff.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSET",
                        help="Show changes from this revision")
    p_diff.add_argument("-t", "--to", dest="to", default=None, metavar="REVSET",
                        help="Show changes to this revision")
    p_diff.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_diff.add_argument("--stat", action="store_true", help="Show histogram")
    p_diff.add_argument("--name-only", action="store_true", help="Show only path")
    p_diff.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_diff.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_diff.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict diff to")
    p_diff.set_defaults(_handler="pyjj_cli.commands:diff")

    p_show = sub.add_parser("show", help="Show revision metadata and diff")
    p_show.add_argument("revisions", nargs="*", metavar="REVSETS", help="Revisions to show (default: @)")
    p_show.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_show.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_show.add_argument("--stat", action="store_true", help="Show histogram")
    p_show.add_argument("--name-only", action="store_true", help="Show only path")
    p_show.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_show.add_argument("--no-patch", action="store_true", help="Do not show patch")
    p_show.set_defaults(_handler="pyjj_cli.commands:show")
