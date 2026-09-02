import argparse


def _file_help(args):
    import sys
    print("usage: pyjj file {list,show,annotate}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_file = sub.add_parser("file", help="File operations")
    p_file.set_defaults(_handler="pyjj_cli.cli.file:_file_help")
    file_sub = p_file.add_subparsers(dest="file_command")

    p_flist = file_sub.add_parser("list", help="List files in a revision")
    p_flist.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to list files for (default: @)")
    p_flist.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict to")
    p_flist.set_defaults(_handler="pyjj_cli.commands.file.list:file_list")

    p_fshow = file_sub.add_parser("show", help="Print contents of files in a revision")
    p_fshow.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to show files from (default: @)")
    p_fshow.add_argument("filesets", nargs="+", metavar="FILESETS", help="Paths to show")
    p_fshow.set_defaults(_handler="pyjj_cli.commands.file.show:file_show")

    p_fannot = file_sub.add_parser("annotate", help="Show line annotation (blame)")
    p_fannot.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                           help="Revision to annotate (default: @)")
    p_fannot.add_argument("path", metavar="PATH", help="File to annotate")
    p_fannot.set_defaults(_handler="pyjj_cli.commands.file.annotate:file_annotate")

    p_fchmod = file_sub.add_parser("chmod", help="Sets or removes the executable bit for paths in the repo")
    p_fchmod.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET", help="Revision to update (default: @)")
    p_fchmod.add_argument("mode", choices=["n", "x", "normal", "executable"], help="n: non-executable, x: executable")
    p_fchmod.add_argument("paths", nargs="+", help="Paths to update")
    p_fchmod.set_defaults(_handler="pyjj_cli.commands.file.chmod:file_chmod")

    p_ftrack = file_sub.add_parser("track", help="Start tracking specified paths in the working copy")
    p_ftrack.add_argument("paths", nargs="+", help="Paths to track")
    p_ftrack.add_argument("--include-ignored", dest="include_ignored", action="store_true", help="Track ignored or too large files")
    p_ftrack.set_defaults(_handler="pyjj_cli.commands.file.track:file_track")

    p_funtrack = file_sub.add_parser("untrack", help="Stop tracking specified paths in the working copy")
    p_funtrack.add_argument("paths", nargs="+", help="Paths to untrack")
    p_funtrack.set_defaults(_handler="pyjj_cli.commands.file.untrack:file_untrack")

    p_fsearch = file_sub.add_parser("search", help="Search for content in files")
    p_fsearch.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to search in (default: @)")
    p_fsearch.add_argument("-p", "--pattern", dest="pattern", required=True, help="Pattern to search for")
    p_fsearch.add_argument("filesets", nargs="*", help="Paths to restrict to")
    p_fsearch.add_argument("--name-only", dest="name_only", action="store_true", help="Print only file paths")
    p_fsearch.set_defaults(_handler="pyjj_cli.commands.file.search:file_search")
