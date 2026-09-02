import argparse


def _hunk_help(args):
    import sys
    print("usage: pyjj hunk {list,split,commit,squash,schema}", file=sys.stderr)
    return 2


def _hunk_root(args):
    if getattr(args, "json_schema", False):
        # lazy load heavy handler
        from pyjj_cli.commands import hunk_schema

        return hunk_schema(args)
    return _hunk_help(args)


def add_parsers(sub) -> None:
    p_hunk = sub.add_parser("hunk", help="Hunk-level selection for AI agents (like jj-hunk)")
    p_hunk.add_argument("--json-schema", action="store_true", help="Dump JSON schema for LLM tool-calling and exit")
    p_hunk.set_defaults(_handler="pyjj_cli.cli.hunk:_hunk_root")
    hunk_sub = p_hunk.add_subparsers(dest="hunk_command")

    p_hunk_list = hunk_sub.add_parser("list", help="List hunks for a revision")
    p_hunk_list.add_argument("-r", "--revision", default="@", metavar="REVSET",
                             help="Revision to list hunks for (default: @)")
    p_hunk_list.add_argument("--format", choices=["json", "yaml", "text"], default="json",
                             help="Output format (default: json)")
    p_hunk_list.set_defaults(_handler="pyjj_cli.commands.hunk:hunk_list")

    p_hunk_split = hunk_sub.add_parser("split", help="Split a revision with hunk/line spec")
    p_hunk_split.add_argument("-r", "--revision", default="@", metavar="REVSET",
                              help="Revision to split (default: @)")
    p_hunk_split.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                              help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_split.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                              help="Read spec from file (JSON/YAML)")
    p_hunk_split.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_split.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_split.add_argument("message", nargs="?", help="Commit message for first half (or '-' for stdin)")
    p_hunk_split.set_defaults(_handler="pyjj_cli.commands.hunk:hunk_split")

    p_hunk_commit = hunk_sub.add_parser("commit", help="Commit selected hunks from working copy")
    p_hunk_commit.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_commit.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_commit.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_commit.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_commit.add_argument("message", nargs="?", help="Commit message (or '-' for stdin)")
    p_hunk_commit.set_defaults(_handler="pyjj_cli.commands.hunk:hunk_commit")

    p_hunk_squash = hunk_sub.add_parser("squash", help="Squash selected hunks into parent")
    p_hunk_squash.add_argument("-r", "--revision", default="@", metavar="REVSET",
                               help="Revision to squash (default: @)")
    p_hunk_squash.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_squash.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_squash.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_squash.set_defaults(_handler="pyjj_cli.commands.hunk:hunk_squash")

    p_hunk_schema = hunk_sub.add_parser("schema", help="Dump JSON schema for LLM tool-calling")
    p_hunk_schema.add_argument("--format", choices=["json", "yaml"], default="json",
                               help="Output format (default: json)")
    p_hunk_schema.set_defaults(_handler="pyjj_cli.commands.hunk:hunk_schema")
