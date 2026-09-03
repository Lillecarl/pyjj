import argparse

from .flags import Flag, add_flags, add_revision_flag


def _file_help(args):
    import sys
    print("usage: pyjj file {list,show,annotate}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_file = sub.add_parser("file", help="File operations")
    p_file.set_defaults(_handler="pyjj_cli.cli.file:_file_help")
    file_sub = p_file.add_subparsers(dest="file_command")

    p_flist = file_sub.add_parser("list", help="List files in a revision")
    add_revision_flag(p_flist, dest="revision", default="@", help="Revision to list files for (default: @)")
    add_flags(p_flist, {Flag.FILESETS})
    p_flist.set_defaults(_handler="pyjj_cli.commands.file.list:file_list")

    p_fshow = file_sub.add_parser("show", help="Print contents of files in a revision")
    add_revision_flag(p_fshow, dest="revision", default="@", help="Revision to show files from (default: @)")
    add_flags(p_fshow, {Flag.FILESETS_REQUIRED})
    p_fshow.set_defaults(_handler="pyjj_cli.commands.file.show:file_show")

    p_fannot = file_sub.add_parser("annotate", help="Show line annotation (blame)")
    add_revision_flag(p_fannot, dest="revision", default="@", help="Revision to annotate (default: @)")
    p_fannot.add_argument("path", metavar="PATH", help="File to annotate")
    p_fannot.set_defaults(_handler="pyjj_cli.commands.file.annotate:file_annotate")

    p_fchmod = file_sub.add_parser("chmod", help="Sets or removes the executable bit for paths in the repo")
    add_revision_flag(p_fchmod, dest="revision", default="@", help="Revision to update (default: @)")
    p_fchmod.add_argument("mode", choices=["n", "x", "normal", "executable"], help="n: non-executable, x: executable")
    p_fchmod.add_argument("paths", nargs="+", help="Paths to update")
    p_fchmod.set_defaults(_handler="pyjj_cli.commands.file.chmod:file_chmod")

    p_ftrack = file_sub.add_parser("track", help="Start tracking specified paths in the working copy")
    p_ftrack.add_argument("paths", nargs="+", help="Paths to track")
    add_flags(p_ftrack, [Flag.INCLUDE_IGNORED])
    p_ftrack.set_defaults(_handler="pyjj_cli.commands.file.track:file_track")

    p_funtrack = file_sub.add_parser("untrack", help="Stop tracking specified paths in the working copy")
    p_funtrack.add_argument("paths", nargs="+", help="Paths to untrack")
    p_funtrack.set_defaults(_handler="pyjj_cli.commands.file.untrack:file_untrack")

    p_fsearch = file_sub.add_parser("search", help="Search for content in files")
    add_revision_flag(p_fsearch, dest="revision", default="@", help="Revision to search in (default: @)")
    p_fsearch.add_argument("-p", "--pattern", dest="pattern", required=True, help="Pattern to search for")
    add_flags(p_fsearch, {Flag.FILESETS, Flag.NAME_ONLY})
    p_fsearch.set_defaults(_handler="pyjj_cli.commands.file.search:file_search")
