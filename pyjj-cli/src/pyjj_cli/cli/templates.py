import argparse


def _templates_help(args):
    import sys
    print("usage: pyjj templates {list,get,set,edit}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_tpl = sub.add_parser("templates", help="Manage pyjj Jinja templates (pyjj.templates.*)")
    p_tpl.set_defaults(_handler="pyjj_cli.cli.templates:_templates_help")
    tpl_sub = p_tpl.add_subparsers(dest="templates_command")

    p_list = tpl_sub.add_parser("list", help="List pyjj.templates.*")
    p_list.add_argument("--repo", action="store_true", help="List repo config only")
    p_list.set_defaults(_handler="pyjj_cli.commands.templates.templates_list:templates_list")

    p_get = tpl_sub.add_parser("get", help="Get a template")
    p_get.add_argument("name", help="Template name (e.g. log, mycool)")
    p_get.set_defaults(_handler="pyjj_cli.commands.templates.templates_get:templates_get")

    p_set = tpl_sub.add_parser("set", help="Set a template")
    p_set.add_argument("--repo", action="store_true", help="Write to repo config")
    p_set.add_argument("name", help="Template name")
    p_set.add_argument("value", help="Jinja template string")
    p_set.set_defaults(_handler="pyjj_cli.commands.templates.templates_set:templates_set")

    p_edit = tpl_sub.add_parser("edit", help="Edit a template in $EDITOR")
    p_edit.add_argument("--repo", action="store_true", help="Edit repo config")
    p_edit.add_argument("name", help="Template name")
    p_edit.set_defaults(_handler="pyjj_cli.commands.templates.templates_edit:templates_edit")

    p_unset = tpl_sub.add_parser("unset", help="Unset a template")
    p_unset.add_argument("--repo", action="store_true", help="Unset from repo config")
    p_unset.add_argument("name", help="Template name")
    p_unset.set_defaults(_handler="pyjj_cli.commands.templates.templates_unset:templates_unset")
