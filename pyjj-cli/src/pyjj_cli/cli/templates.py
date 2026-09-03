from .flags import add_repo_flag


def _templates_help(args):
    import sys
    print("usage: pyjj templates {list,get,set,edit}", file=sys.stderr)
    return 2


def add_parsers(sub) -> None:
    p_tpl = sub.add_parser("templates", help="Manage pyjj Jinja templates (pyjj.templates.*)")
    p_tpl.set_defaults(_handler="pyjj_cli.cli.templates:_templates_help")
    tpl_sub = p_tpl.add_subparsers(dest="templates_command")

    p_list = tpl_sub.add_parser("list", help="List pyjj.templates.*")
    add_repo_flag(p_list, help="List repo config only")
    p_list.set_defaults(_handler="pyjj_cli.commands.templates.templates_list:templates_list")

    p_get = tpl_sub.add_parser("get", help="Get a template")
    p_get.add_argument("name", help="Template name (e.g. log, mycool)")
    p_get.set_defaults(_handler="pyjj_cli.commands.templates.templates_get:templates_get")

    p_set = tpl_sub.add_parser("set", help="Set a template")
    add_repo_flag(p_set, help="Write to repo config")
    p_set.add_argument("name", help="Template name")
    p_set.add_argument("value", help="Jinja template string")
    p_set.set_defaults(_handler="pyjj_cli.commands.templates.templates_set:templates_set")

    p_edit = tpl_sub.add_parser("edit", help="Edit a template in $EDITOR")
    add_repo_flag(p_edit, help="Edit repo config")
    p_edit.add_argument("name", help="Template name")
    p_edit.set_defaults(_handler="pyjj_cli.commands.templates.templates_edit:templates_edit")

    p_unset = tpl_sub.add_parser("unset", help="Unset a template")
    add_repo_flag(p_unset, help="Unset from repo config")
    p_unset.add_argument("name", help="Template name")
    p_unset.set_defaults(_handler="pyjj_cli.commands.templates.templates_unset:templates_unset")
