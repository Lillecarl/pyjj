import argparse


def add_parsers(sub) -> None:
    p_sq = sub.add_parser("squash", help="Move changes from a revision into another")
    p_sq.add_argument("-r", "--revision", action="append", default=None,
                      metavar="REVSETS", help="Source revisions (default: @)")
    p_sq.add_argument("-f", "--from", dest="from_", action="append", default=None,
                      metavar="REVSETS", help="Source revisions")
    p_sq.add_argument("-t", "--into", dest="into", default=None, metavar="REVSET",
                      help="Destination revision (default: source's parent)")
    p_sq.add_argument("-u", "--use-destination-message", dest="use_destination_message",
                      action="store_true",
                      help="Keep destination's description unchanged")
    p_sq.add_argument("-m", "--message", dest="message", default=None, metavar="MESSAGE",
                      help="Description for the squashed revision")
    p_sq.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to squash (default: all)")
    p_sq.set_defaults(_handler="pyjj_cli.commands:squash")

    p_re = sub.add_parser("rebase", help="Move revisions to a different parent")
    p_re.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move (-r mode)")
    p_re.add_argument("-s", "--source", dest="sources", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move with descendants (-s mode)")
    p_re.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                      metavar="REVSETS", help="Branch to rebase (-b mode)")
    p_re.add_argument("-d", "--destination", dest="destinations", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (-d/--destination)")
    p_re.add_argument("-o", "--onto", dest="ontos", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (--onto synonym for -d)")
    p_re.add_argument("-A", "--insert-after", dest="insert_afters", action="append", default=None,
                      metavar="REVSETS", help="Insert after this revision")
    p_re.add_argument("-B", "--insert-before", dest="insert_befores", action="append", default=None,
                      metavar="REVSETS", help="Insert before this revision")
    p_re.set_defaults(_handler="pyjj_cli.commands:rebase")

    p_ab = sub.add_parser("absorb", help="Move changes from a revision into ancestors")
    p_ab.add_argument("-f", "--from", dest="from_", default="@", metavar="REVSET",
                      help="Source revision to absorb from (default: @)")
    p_ab.add_argument("-t", "--into", "--to", dest="into", default=None, metavar="REVSETS",
                      help="Destination revisions to absorb into (default: mutable())")
    p_ab.add_argument("-i", "--interactive", action="store_true",
                      help="Interactively choose which parts to absorb")
    p_ab.add_argument("--tool", dest="tool", default=None, metavar="NAME",
                      help="Diff editor for interactive selection")
    p_ab.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to absorb (default: all)")
    p_ab.set_defaults(_handler="pyjj_cli.commands:absorb")

    p_fix = sub.add_parser("fix", help="Update files with formatting fixes")
    p_fix.add_argument("-s", "--source", dest="source", default=None, metavar="REVSETS",
                       help="Fix files in revision(s) and descendants (default: reachable(@, mutable()))")
    p_fix.add_argument("--include-unchanged-files", dest="include_unchanged", action="store_true",
                       help="Fix unchanged files as well")
    p_fix.add_argument("filesets", nargs="*", metavar="FILESETS",
                       help="Paths to fix (default: all)")
    p_fix.set_defaults(_handler="pyjj_cli.commands:fix")

    p_rev = sub.add_parser("revert", help="Apply the reverse of given revisions")
    p_rev.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                       metavar="REVSETS", required=True,
                       help="Revision(s) to revert")
    p_rev.add_argument("-o", "--onto", dest="ontos", action="append", default=None,
                       metavar="REVSETS", help="Apply reverse on top of this revision")
    p_rev.add_argument("-d", "--destination", dest="destinations", action="append", default=None,
                       metavar="REVSETS", help="Alias for --onto")
    p_rev.add_argument("-A", "--insert-after", dest="insert_afters", action="append", default=None,
                       metavar="REVSETS", help="Insert after this revision")
    p_rev.add_argument("-B", "--insert-before", dest="insert_befores", action="append", default=None,
                       metavar="REVSETS", help="Insert before this revision")
    p_rev.set_defaults(_handler="pyjj_cli.commands:revert")

    p_abandon = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p_abandon.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                      help="Revisions to abandon (default: @)")
    p_abandon.set_defaults(_handler="pyjj_cli.commands:abandon")

    p_dup = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p_dup.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                       help="Revisions to duplicate (default: @)")
    p_dup.set_defaults(_handler="pyjj_cli.commands:duplicate")

    p_res = sub.add_parser("restore", help="Restore paths from another revision")
    p_res.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                       help="Revision to restore from (default: @-)")
    p_res.add_argument("--into", dest="into", default="@", metavar="REVSET",
                       help="Revision to restore into (default: @)")
    p_res.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths to restore (default: all)")
    p_res.set_defaults(_handler="pyjj_cli.commands:restore")

    p_spl = sub.add_parser("split", help="Split a revision in two")
    p_spl.add_argument("-r", "--revision", default=None, metavar="REVSETS",
                       help="Revision to split (default: @)")
    p_spl.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description of the first half")
    p_spl.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor for selecting changes (no FILESETS)")
    p_spl.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths going into the first half")
    p_spl.set_defaults(_handler="pyjj_cli.commands:split")
