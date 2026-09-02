import argparse


def add_parsers(sub) -> None:
    p_desc = sub.add_parser("describe", aliases=["desc"], help="Set commit descriptions")
    p_desc.add_argument("-r", "--revision", dest="revisions_opt", action="append",
                        default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p_desc.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                        help="Revisions to describe (default: @)")
    p_desc.add_argument("-m", "--message", dest="messages", action="append",
                        default=None, metavar="MESSAGE",
                        help="Description text (repeatable; paragraphs joined)")
    p_desc.add_argument("--stdin", action="store_true",
                        help="Read description from stdin")
    p_desc.set_defaults(_handler="pyjj_cli.commands.describe:describe")

    p_new = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p_new.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                       help="Parent revisions (default: @)")
    p_new.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                       help="Description of the new change")
    p_new.set_defaults(_handler="pyjj_cli.commands.describe:new")

    p_edit = sub.add_parser("edit", help="Edit (check out) a specific revision")
    p_edit.add_argument("revision_pos", metavar="REVSETS",
                        help="The revision to edit")
    p_edit.set_defaults(_handler="pyjj_cli.commands.rewrite:edit")

    p_com = sub.add_parser("commit",
                           help="Describe @ and create a new empty change on top")
    p_com.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description text")
    p_com.add_argument("--editor", action="store_true",
                       help="Open an editor to edit the description")
    p_com.add_argument("-i", "--interactive", action="store_true",
                       help="Interactively choose which changes to include")
    p_com.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor to use (implies --interactive)")
    p_com.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths staying in the current commit")
    p_com.set_defaults(_handler="pyjj_cli.commands.rewrite:commit")

    p_de = sub.add_parser("diffedit",
                          help="Edit the diff between two revisions in a diff editor")
    p_de.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                      help="Show the diff FROM this revision (default: @-)")
    p_de.add_argument("--to", dest="into", default="@", metavar="REVSET",
                      help="Apply edits TO this revision (default: @)")
    p_de.add_argument("--tool", default=None, metavar="NAME",
                      help="Diff editor to use")
    p_de.set_defaults(_handler="pyjj_cli.commands.history:diffedit")

    p_rslv = sub.add_parser("resolve",
                            help="Resolve conflicted files with an external merge tool")
    p_rslv.add_argument("-r", "--revision", default="@", metavar="REVSET",
                        help="The revision to resolve conflicts in (default: @)")
    p_rslv.add_argument("-l", "--list", dest="list_", action="store_true",
                        help="Instead of resolving conflicts, list all the conflicts")
    p_rslv.add_argument("--tool", default=None, metavar="NAME",
                        help="3-way merge tool to be used; :ours and :theirs pick side #1/#2")
    p_rslv.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                        help="Only resolve conflicts in these paths")
    p_rslv.set_defaults(_handler="pyjj_cli.commands.resolve:resolve")

    p_sign = sub.add_parser("sign", help="Cryptographically sign a revision")
    p_sign.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Revision to sign (can be repeated)")
    p_sign.add_argument("--key", dest="key", default=None, help=argparse.SUPPRESS)
    p_sign.set_defaults(_handler="pyjj_cli.commands.crypto:sign")

    p_unsign = sub.add_parser("unsign", help="Drop a cryptographic signature")
    p_unsign.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Revision to unsign (can be repeated)")
    p_unsign.set_defaults(_handler="pyjj_cli.commands.crypto:unsign")

    p_meta = sub.add_parser("metaedit", help="Modify metadata of a revision without changing content")
    p_meta.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to modify")
    p_meta.add_argument("--author", dest="author", default=None, help="Set author")
    p_meta.add_argument("--committer", dest="committer", default=None, help="Set committer")
    p_meta.set_defaults(_handler="pyjj_cli.commands.crypto:metaedit")

    p_version = sub.add_parser("version", help="Show version information")
    p_version.set_defaults(_handler="pyjj_cli.commands.crypto:version")

    # root shortcut
    p_root = sub.add_parser("root", help="Show the current workspace root directory (shortcut for `jj workspace root`)")
    p_root.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_root")
