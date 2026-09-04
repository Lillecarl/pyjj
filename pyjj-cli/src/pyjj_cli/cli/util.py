"""`jj util`: infrequently used commands.

Only `backend name`, `exec`, `gc` and `snapshot` are implemented. The
rest keep the old stub behaviour, so an unimplemented subcommand still
exits 2 -- and so does an unknown one, which argparse rejects on its
own.
"""
import argparse
import sys


def _util_help(args):
    print("usage: pyjj util {backend,exec,gc,snapshot}", file=sys.stderr)
    return 2


def _stub(name: str):
    def _h(args):
        print(f"Error: util {name} is not yet supported", file=sys.stderr)
        return 2
    return _h


def _backend_help(args):
    print("usage: pyjj util backend {name}", file=sys.stderr)
    return 2


def _stub_completion(args):
    return _stub("completion")(args)


def _stub_config_schema(args):
    return _stub("config-schema")(args)


def _stub_install_man_pages(args):
    return _stub("install-man-pages")(args)


def _stub_markdown_help(args):
    return _stub("markdown-help")(args)


def add_parsers(sub) -> None:
    p = sub.add_parser(
        "util",
        help="Infrequently used commands such as for generating shell completions",
    )
    p.set_defaults(_handler="pyjj_cli.cli.util:_util_help")
    util_sub = p.add_subparsers(dest="util_command")

    p_gc = util_sub.add_parser("gc", help="Run backend-dependent garbage collection")
    p_gc.add_argument("--expire", default=None, metavar="EXPIRE",
                      help="Time threshold; only 'now' is accepted")
    p_gc.set_defaults(_handler="pyjj_cli.commands.util.gc:util_gc")

    p_snapshot = util_sub.add_parser(
        "snapshot", help="Snapshot the working copy if needed")
    p_snapshot.set_defaults(
        _handler="pyjj_cli.commands.util.snapshot:util_snapshot")

    p_exec = util_sub.add_parser("exec", help="Execute an external command via jj")
    p_exec.add_argument("command_name", nargs="?", default=None,
                        metavar="COMMAND", help="External command to execute")
    p_exec.add_argument("command_args", nargs=argparse.REMAINDER,
                        metavar="ARGS",
                        help="Arguments to pass to the external command")
    p_exec.set_defaults(_handler="pyjj_cli.commands.util.exec:util_exec")

    p_backend = util_sub.add_parser(
        "backend", help="Commands relating to the backend used in the current repo")
    p_backend.set_defaults(_handler="pyjj_cli.cli.util:_backend_help")
    backend_sub = p_backend.add_subparsers(dest="backend_command")
    p_backend_name = backend_sub.add_parser(
        "name", help="Print the name of the backend used in the current repo")
    p_backend_name.set_defaults(
        _handler="pyjj_cli.commands.util.backend:util_backend_name")

    for name, handler in (
        ("completion", "_stub_completion"),
        ("config-schema", "_stub_config_schema"),
        ("install-man-pages", "_stub_install_man_pages"),
        ("markdown-help", "_stub_markdown_help"),
    ):
        p_stub = util_sub.add_parser(name, help=f"jj util {name}")
        p_stub.add_argument("rest", nargs="*", help="Not yet supported")
        p_stub.set_defaults(_handler=f"pyjj_cli.cli.util:{handler}")
