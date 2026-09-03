import argparse

from .flags import Flag, add_flags, add_revision_flag


def _tag_help(args):
    import sys
    print("usage: pyjj tag {list,set,delete}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_tag = sub.add_parser("tag", help="Manage tags")
    p_tag.set_defaults(_handler="pyjj_cli.cli.tag:_tag_help")
    tag_sub = p_tag.add_subparsers(dest="tag_command")
    p_tag_list = tag_sub.add_parser("list", help="List tags")
    p_tag_list.add_argument("names", nargs="*", help="Tags to list")
    p_tag_list.set_defaults(_handler="pyjj_cli.commands.tag.tag_list:tag_list")
    p_tag_set = tag_sub.add_parser("set", help="Create or update tags")
    p_tag_set.add_argument("names", nargs="+", help="Tags to set")
    add_revision_flag(p_tag_set, dest="revision", default="@", help="Revision to point at (default: @)")
    p_tag_set.set_defaults(_handler="pyjj_cli.commands.tag.tag_set:tag_set")
    p_tag_delete = tag_sub.add_parser("delete", help="Delete existing tags")
    p_tag_delete.add_argument("names", nargs="+", help="Tags to delete")
    p_tag_delete.set_defaults(_handler="pyjj_cli.commands.tag.tag_delete:tag_delete")
    p_tag_track = tag_sub.add_parser("track", help="Start tracking given remote tags")
    p_tag_track.add_argument("names", nargs="+", help="Tags to track")
    add_flags(p_tag_track, [Flag.REMOTE])
    p_tag_track.set_defaults(_handler="pyjj_cli.commands.tag.tag_track:tag_track")
    p_tag_untrack = tag_sub.add_parser("untrack", help="Stop tracking given remote tags")
    p_tag_untrack.add_argument("names", nargs="+", help="Tags to untrack")
    add_flags(p_tag_untrack, [Flag.REMOTE])
    p_tag_untrack.set_defaults(_handler="pyjj_cli.commands.tag.tag_untrack:tag_untrack")
