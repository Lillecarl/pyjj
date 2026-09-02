import argparse


def _bm_help(args):
    import sys
    print("usage: pyjj bookmark {create,set,delete,forget,list,move,rename}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_bm = sub.add_parser("bookmark", help="Manage bookmarks")
    p_bm.set_defaults(_handler="pyjj_cli.cli.bookmark:_bm_help")
    bm_sub = p_bm.add_subparsers(dest="bookmark_command")

    p_bmc = bm_sub.add_parser("create", help="Create a new bookmark")
    p_bmc.add_argument("names", nargs="+", metavar="NAMES")
    p_bmc.add_argument("-r", "--revision", default="@", metavar="REVSET",
                       help="Revision to point at (default: @)")
    p_bmc.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bms = bm_sub.add_parser("set", help="Move an existing bookmark")
    p_bms.add_argument("name")
    p_bms.add_argument("-r", "--revision", required=True, metavar="REVSET")
    p_bms.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bmd = bm_sub.add_parser("delete", help="Delete a bookmark")
    p_bmd.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to delete")
    p_bmd.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bmf = bm_sub.add_parser("forget", help="Forget a bookmark")
    p_bmf.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to forget")
    p_bmf.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bml = bm_sub.add_parser("list", help="List bookmarks")
    p_bml.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to list")
    p_bml.add_argument("-a", "--all-remotes", action="store_true", help=argparse.SUPPRESS)
    p_bml.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bmm = bm_sub.add_parser("move", help="Move bookmarks to a revision")
    p_bmm.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to move")
    p_bmm.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSETS",
                       help=argparse.SUPPRESS)
    p_bmm.add_argument("-t", "--to", dest="to", default="@", metavar="REVSET",
                       help="Target revision (default: @)")
    p_bmm.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bmr = bm_sub.add_parser("rename", help="Rename a bookmark")
    p_bmr.add_argument("old", metavar="OLD", help="Old bookmark name")
    p_bmr.add_argument("new", metavar="NEW", help="New bookmark name")
    p_bmr.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark")

    p_bmt = bm_sub.add_parser("track", help="Start tracking given remote bookmarks")
    p_bmt.add_argument("names", nargs="+", help="Bookmarks to track")
    p_bmt.add_argument("--remote", dest="remote", default=None, help="Remote to track")
    p_bmt.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark_track")

    p_bmut = bm_sub.add_parser("untrack", help="Stop tracking given remote bookmarks")
    p_bmut.add_argument("names", nargs="+", help="Bookmarks to untrack")
    p_bmut.add_argument("--remote", dest="remote", default=None, help="Remote to untrack")
    p_bmut.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark_untrack")

    p_bma = bm_sub.add_parser("advance", help="Advance the closest bookmarks to a target revision")
    p_bma.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to advance to (default: @)")
    p_bma.set_defaults(_handler="pyjj_cli.commands.bookmark:bookmark_advance")
