def add_parsers(sub) -> None:
    p_graph = sub.add_parser(
        "graph", help="Compare the repository against a Graphviz DOT graph")
    p_graph.set_defaults(_handler="pyjj_cli.cli.graph:_graph_root")
    graph_sub = p_graph.add_subparsers(dest="graph_command")

    p_plan = graph_sub.add_parser(
        "plan", help="Print the rebases that would make the repository "
                     "match a DOT graph")
    p_plan.add_argument("file", metavar="FILE",
                        help="The DOT graph to compare against, or - for "
                             "standard input")
    p_plan.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    p_plan.set_defaults(_handler="pyjj_cli.commands.graph.plan:plan")

    p_apply = graph_sub.add_parser(
        "apply", help="Reshape the repository to match a DOT graph")
    p_apply.add_argument("file", metavar="FILE",
                         help="The DOT graph to match, or - for standard "
                              "input")
    p_apply.add_argument("--dry-run", action="store_true",
                         help="Print what would be rebased and stop")
    p_apply.add_argument("--ignore-immutable", action="store_true",
                         help="Rewrite commits the immutable_heads config "
                              "protects (refused by default)")
    p_apply.add_argument("--allow-conflicts", action="store_true",
                         help="Keep the result when the reshape leaves a "
                              "conflict (rolled back by default)")
    p_apply.add_argument("--format", choices=["text", "json"], default="text",
                         help="Output format (default: text)")
    p_apply.set_defaults(_handler="pyjj_cli.commands.graph.apply:apply")


def _graph_root(args) -> int:
    import sys
    print("usage: pyjj graph {plan,apply} <FILE>", file=sys.stderr)
    return 2
