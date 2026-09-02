import argparse


def _workspace_help(args):
    import sys
    print("usage: pyjj workspace {add,forget,list,rename,root,update-stale}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_ws = sub.add_parser("workspace", help="Commands for working with workspaces")
    p_ws.set_defaults(_handler="pyjj_cli.cli.workspace:_workspace_help")
    ws_sub = p_ws.add_subparsers(dest="workspace_command")
    p_ws_add = ws_sub.add_parser("add", help="Add a workspace")
    p_ws_add.add_argument("destination", help="Where to create the new workspace")
    p_ws_add.add_argument("--name", dest="name", default=None, help="A name for the workspace")
    p_ws_add.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Parent revisions for the new workspace")
    p_ws_add.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_add")
    p_ws_forget = ws_sub.add_parser("forget", help="Stop tracking a workspace")
    p_ws_forget.add_argument("names", nargs="+", help="Workspaces to forget")
    p_ws_forget.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_forget")
    p_ws_list = ws_sub.add_parser("list", help="List workspaces")
    p_ws_list.add_argument("-T", "--template", dest="template", default=None, help=argparse.SUPPRESS)
    p_ws_list.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_list")
    p_ws_rename = ws_sub.add_parser("rename", help="Renames the current workspace")
    p_ws_rename.add_argument("new_name", help="New workspace name")
    p_ws_rename.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_rename")
    p_ws_root = ws_sub.add_parser("root", help="Show the workspace root directory")
    p_ws_root.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_root")
    p_ws_update = ws_sub.add_parser("update-stale", help="Update a workspace that has become stale")
    p_ws_update.set_defaults(_handler="pyjj_cli.commands.workspace:workspace_update_stale")
