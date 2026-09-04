"""`jj util`: infrequently used commands.

Only `gc` and `snapshot` are implemented. The rest keep the old stub
behaviour, so an
unimplemented subcommand still exits 2 -- and so does an unknown one,
which argparse rejects on its own.
"""
import sys


def _util_help(args):
    print("usage: pyjj util {gc,snapshot}", file=sys.stderr)
    return 2


def _stub(name: str):
    def _h(args):
        print(f"Error: util {name} is not yet supported", file=sys.stderr)
        return 2
    return _h


def _stub_backend(args):
    return _stub("backend")(args)


def _stub_completion(args):
    return _stub("completion")(args)


def _stub_config_schema(args):
    return _stub("config-schema")(args)


def _stub_exec(args):
    return _stub("exec")(args)


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

    for name, handler in (
        ("backend", "_stub_backend"),
        ("completion", "_stub_completion"),
        ("config-schema", "_stub_config_schema"),
        ("exec", "_stub_exec"),
        ("install-man-pages", "_stub_install_man_pages"),
        ("markdown-help", "_stub_markdown_help"),
    ):
        p_stub = util_sub.add_parser(name, help=f"jj util {name}")
        p_stub.add_argument("rest", nargs="*", help="Not yet supported")
        p_stub.set_defaults(_handler=f"pyjj_cli.cli.util:{handler}")
