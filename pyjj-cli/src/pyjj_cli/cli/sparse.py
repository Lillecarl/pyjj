import argparse


def _sparse_help(args):
    import sys
    print("usage: pyjj sparse {list,set,reset,edit}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_sparse = sub.add_parser("sparse", help="Manage which paths are present in the working copy")
    p_sparse.set_defaults(_handler="pyjj_cli.cli.sparse:_sparse_help")
    sparse_sub = p_sparse.add_subparsers(dest="sparse_command")
    p_sparse_list = sparse_sub.add_parser("list", help="List the patterns that are currently present")
    p_sparse_list.set_defaults(_handler="pyjj_cli.commands:sparse_list")
    p_sparse_set = sparse_sub.add_parser("set", help="Update the patterns that are present")
    p_sparse_set.add_argument("--add", dest="adds", action="append", default=None, metavar="ADD", help="Patterns to add")
    p_sparse_set.add_argument("--remove", dest="removes", action="append", default=None, metavar="REMOVE", help="Patterns to remove")
    p_sparse_set.add_argument("--clear", action="store_true", help="Include no files (combine with --add)")
    p_sparse_set.set_defaults(_handler="pyjj_cli.commands:sparse_set")
    p_sparse_reset = sparse_sub.add_parser("reset", help="Reset the patterns to include all files")
    p_sparse_reset.set_defaults(_handler="pyjj_cli.commands:sparse_reset")
    p_sparse_edit = sparse_sub.add_parser("edit", help="Start an editor to update the patterns")
    p_sparse_edit.set_defaults(_handler="pyjj_cli.commands:sparse_edit")
