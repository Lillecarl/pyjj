from ..flags import Flag, add_flags


def register(sub) -> None:
    p = sub.add_parser("evolog", help="Show how a change has evolved over time")
    add_flags(p, [Flag.REVISIONS, Flag.LIMIT])
    # jj drives `evolog` from `templates.evolog`; pyjj-cli uses Jinja
    # for the same job, under `pyjj.templates.evolog`.
    p.add_argument("-T", "--template", default=None, metavar="TEMPLATE",
                   help="Render each entry with this Jinja template")
    p.add_argument("--no-graph", action="store_true",
                   help="Print entries without the graph")
    p.set_defaults(_handler="pyjj_cli.commands.operation.evolog:evolog")
