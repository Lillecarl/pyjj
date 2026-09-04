def register(sub) -> None:
    # `op` — short form
    p_op = sub.add_parser("op", help="Operation log commands")
    p_op.set_defaults(_handler="pyjj_cli.cli.operation:_op_help")
    op_sub = p_op.add_subparsers(dest="op_command")
    p_opr = op_sub.add_parser("restore", help="Restore to the state of an operation")
    p_opr.add_argument("operation_pos", metavar="OPERATION", help="The operation to restore to")
    p_opr.set_defaults(_handler="pyjj_cli.commands.operation.op_restore:op_restore")
    p_op_log2 = op_sub.add_parser("log", help="Show the operation log")
    p_op_log2.set_defaults(_handler="pyjj_cli.commands.operation.op_log:op_log")
    p_op_show2 = op_sub.add_parser("show", help="Show changes to the repository in an operation")
    p_op_show2.add_argument("operation", nargs="?", help="Operation to show")
    p_op_show2.set_defaults(_handler="pyjj_cli.commands.operation.op_show:op_show")
    p_op_abandon2 = op_sub.add_parser("abandon", help="Abandon operation history")
    p_op_abandon2.add_argument("operations", nargs="+", help="Operations to abandon")
    p_op_abandon2.set_defaults(_handler="pyjj_cli.commands.operation.op_abandon:op_abandon")
    p_op_diff2 = op_sub.add_parser("diff", help="Compare changes to the repository between two operations")
    p_op_diff2.add_argument("--operation", "--op", dest="operation", default=None,
                          metavar="OPERATION",
                          help="Show repository changes in this operation, compared to its parent")
    p_op_diff2.add_argument("-f", "--from", dest="from_", default=None, metavar="OPERATION",
                          help="Show repository changes from this operation")
    p_op_diff2.add_argument("-t", "--to", dest="to", default=None, metavar="OPERATION",
                          help="Show repository changes to this operation")
    p_op_diff2.add_argument("-G", "--no-graph", action="store_true",
                          help="Don't show the graph, show a flat list of modified changes")
    p_op_diff2.add_argument("--show-changes-in", default=None, metavar="REVSETS",
                          help="Show only changed revisions matching this revset")
    p_op_diff2.set_defaults(_handler="pyjj_cli.commands.operation.op_diff:op_diff")
    p_op_integrate2 = op_sub.add_parser("integrate", help="Make an operation part of the operation log")
    p_op_integrate2.add_argument("operation", help="Operation to integrate")
    p_op_integrate2.set_defaults(_handler="pyjj_cli.commands.operation.op_integrate:op_integrate")
    p_op_revert2 = op_sub.add_parser("revert", help="Create a new operation that reverts an earlier operation")
    p_op_revert2.add_argument("operation", nargs="?", default="@",
                              help="Operation to revert (default: @)")
    p_op_revert2.set_defaults(_handler="pyjj_cli.commands.operation.op_revert:op_revert")

    # `operation` — long form (duplicate of `op` for compatibility)
    p_oplog = sub.add_parser("operation", help="Commands for working with the operation log")
    p_oplog.set_defaults(_handler="pyjj_cli.cli.operation:_op_help")
    oplog_sub = p_oplog.add_subparsers(dest="oplog_command")
    p_oplog_log = oplog_sub.add_parser("log", help="Show the operation log")
    p_oplog_log.set_defaults(_handler="pyjj_cli.commands.operation.op_log:op_log")
    p_oplog_show = oplog_sub.add_parser("show", help="Show changes to the repository in an operation")
    p_oplog_show.add_argument("operation", nargs="?", help="Operation to show")
    p_oplog_show.set_defaults(_handler="pyjj_cli.commands.operation.op_show:op_show")
    p_oplog_abandon = oplog_sub.add_parser("abandon", help="Abandon operation history")
    p_oplog_abandon.add_argument("operations", nargs="+", help="Operations to abandon")
    p_oplog_abandon.set_defaults(_handler="pyjj_cli.commands.operation.op_abandon:op_abandon")
    p_oplog_diff = oplog_sub.add_parser("diff", help="Compare changes to the repository between two operations")
    p_oplog_diff.add_argument("--operation", "--op", dest="operation", default=None,
                          metavar="OPERATION",
                          help="Show repository changes in this operation, compared to its parent")
    p_oplog_diff.add_argument("-f", "--from", dest="from_", default=None, metavar="OPERATION",
                          help="Show repository changes from this operation")
    p_oplog_diff.add_argument("-t", "--to", dest="to", default=None, metavar="OPERATION",
                          help="Show repository changes to this operation")
    p_oplog_diff.add_argument("-G", "--no-graph", action="store_true",
                          help="Don't show the graph, show a flat list of modified changes")
    p_oplog_diff.add_argument("--show-changes-in", default=None, metavar="REVSETS",
                          help="Show only changed revisions matching this revset")
    p_oplog_diff.set_defaults(_handler="pyjj_cli.commands.operation.op_diff:op_diff")
    p_oplog_restore2 = oplog_sub.add_parser("restore", help="Restore to the state of an operation")
    p_oplog_restore2.add_argument("operation", help="Operation to restore to")
    p_oplog_restore2.set_defaults(_handler="pyjj_cli.commands.operation.op_restore:op_restore")
    p_oplog_integrate = oplog_sub.add_parser("integrate", help="Make an operation part of the operation log")
    p_oplog_integrate.add_argument("operation", help="Operation to integrate")
    p_oplog_integrate.set_defaults(_handler="pyjj_cli.commands.operation.op_integrate:op_integrate")
    p_oplog_revert = oplog_sub.add_parser("revert", help="Create a new operation that reverts an earlier operation")
    p_oplog_revert.add_argument("operation", nargs="?", default="@",
                                help="Operation to revert (default: @)")
    p_oplog_revert.set_defaults(_handler="pyjj_cli.commands.operation.op_revert:op_revert")
