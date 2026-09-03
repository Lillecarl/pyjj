import argparse

from .flags import Flag, add_flags


def add_parsers(sub) -> None:
    p_desc = sub.add_parser("describe", aliases=["desc"], help="Set commit descriptions")
    p_desc.add_argument("-r", "--revision", dest="revisions_opt", action="append",
                        default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p_desc.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                        help="Revisions to describe (default: @)")
    add_flags(p_desc, [Flag.MESSAGE_APPEND, Flag.STDIN])
    p_desc.set_defaults(_handler="pyjj_cli.commands.describe.describe:describe")

    p_new = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p_new.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                       help="Parent revisions (default: @)")
    p_new.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                       help="Description of the new change")
    p_new.set_defaults(_handler="pyjj_cli.commands.describe.new:new")

    p_edit = sub.add_parser("edit", help="Edit (check out) a specific revision")
    p_edit.add_argument("revision_pos", metavar="REVSETS",
                        help="The revision to edit")
    p_edit.set_defaults(_handler="pyjj_cli.commands.rewrite.edit:edit")

    p_com = sub.add_parser("commit",
                           help="Describe @ and create a new empty change on top")
    add_flags(p_com, [Flag.MESSAGE])
    p_com.add_argument("--editor", action="store_true",
                       help="Open an editor to edit the description")
    p_com.add_argument("-i", "--interactive", action="store_true",
                       help="Interactively choose which changes to include")
    add_flags(p_com, [Flag.TOOL])
    p_com.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths staying in the current commit")
    p_com.set_defaults(_handler="pyjj_cli.commands.rewrite.commit:commit")

    p_de = sub.add_parser("diffedit",
                          help="Edit the diff between two revisions in a diff editor")
    p_de.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                      help="Show the diff FROM this revision (default: @-)")
    p_de.add_argument("--to", dest="into", default="@", metavar="REVSET",
                      help="Apply edits TO this revision (default: @)")
    add_flags(p_de, [Flag.TOOL])
    p_de.set_defaults(_handler="pyjj_cli.commands.resolve.diffedit:diffedit")

    p_rslv = sub.add_parser("resolve",
                            help="Resolve conflicted files with an external merge tool")
    p_rslv.add_argument("-r", "--revision", default="@", metavar="REVSET",
                        help="The revision to resolve conflicts in (default: @)")
    p_rslv.add_argument("-l", "--list", dest="list_", action="store_true",
                        help="Instead of resolving conflicts, list all the conflicts")
    add_flags(p_rslv, [Flag.TOOL])
    p_rslv.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                        help="Only resolve conflicts in these paths")
    p_rslv.set_defaults(_handler="pyjj_cli.commands.resolve.resolve:resolve")

    p_sign = sub.add_parser("sign", help="Cryptographically sign a revision")
    add_flags(p_sign, [Flag.REVISION_APPEND, Flag.KEY])
    p_sign.set_defaults(_handler="pyjj_cli.commands.crypto.sign:sign")

    p_unsign = sub.add_parser("unsign", help="Drop a cryptographic signature")
    add_flags(p_unsign, [Flag.REVISION_APPEND])
    p_unsign.set_defaults(_handler="pyjj_cli.commands.crypto.unsign:unsign")

    p_meta = sub.add_parser("metaedit", help="Modify metadata of a revision without changing content")
    p_meta.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to modify")
    add_flags(p_meta, [Flag.AUTHOR, Flag.COMMITTER])
    p_meta.set_defaults(_handler="pyjj_cli.commands.crypto.metaedit:metaedit")

    p_version = sub.add_parser("version", help="Show version information")
    p_version.set_defaults(_handler="pyjj_cli.commands.crypto.version:version")

    # root shortcut
    p_root = sub.add_parser("root", help="Show the current workspace root directory (shortcut for `jj workspace root`)")
    p_root.set_defaults(_handler="pyjj_cli.commands.workspace.workspace_root:workspace_root")
