import argparse

from .flags import Flag, add_flags


def _config_help(args):
    import sys
    print("usage: pyjj config {get,list,set,unset}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_config = sub.add_parser("config", help="Manage config options")
    p_config.set_defaults(_handler="pyjj_cli.cli.config:_config_help")
    config_sub = p_config.add_subparsers(dest="config_command")
    p_cfg_get = config_sub.add_parser("get", help="Get the value of a given config option")
    p_cfg_get.add_argument("name", help="Config option name")
    p_cfg_get.set_defaults(_handler="pyjj_cli.commands.config.config_get:config_get")
    p_cfg_list = config_sub.add_parser("list", help="List variables set in config files")
    p_cfg_list.add_argument("name", nargs="?", help="Optional config name prefix")
    p_cfg_list.set_defaults(_handler="pyjj_cli.commands.config.config_list:config_list")
    p_cfg_set = config_sub.add_parser("set", help="Update config file to set the given option")
    add_flags(p_cfg_set, [Flag.REPO_FLAG])
    p_cfg_set.add_argument("name", help="Config option name")
    p_cfg_set.add_argument("value", help="Config value")
    p_cfg_set.set_defaults(_handler="pyjj_cli.commands.config.config_set:config_set")
    p_cfg_unset = config_sub.add_parser("unset", help="Update config file to unset the given option")
    add_flags(p_cfg_unset, [Flag.REPO_FLAG])
    p_cfg_unset.add_argument("name", help="Config option name")
    p_cfg_unset.set_defaults(_handler="pyjj_cli.commands.config.config_unset:config_unset")
    p_cfg_edit = config_sub.add_parser("edit", help="Start an editor on a jj config file")
    p_cfg_edit.set_defaults(_handler="pyjj_cli.cli.config:_stub_edit")
    p_cfg_gc = config_sub.add_parser("gc", help="Find and optionally delete repo-level config")
    p_cfg_gc.set_defaults(_handler="pyjj_cli.cli.config:_stub_gc")
    p_cfg_path = config_sub.add_parser("path", help="Print the paths to the config files")
    p_cfg_path.set_defaults(_handler="pyjj_cli.cli.config:_stub_path")


def _stub_edit(args):
    import sys
    print("Error: config edit is not yet supported", file=sys.stderr)
    return 2


def _stub_gc(args):
    import sys
    print("Error: config gc is not yet supported", file=sys.stderr)
    return 2


def _stub_path(args):
    import sys
    print("Error: config path is not yet supported", file=sys.stderr)
    return 2
