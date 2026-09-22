def add_parsers(sub) -> None:
    p = sub.add_parser(
        "python", help="Run a Python script with pyjj importable")
    p.add_argument("file", nargs="?", metavar="FILE",
                   help="Script to run, or - for standard input "
                        "(the default)")
    p.add_argument("-c", dest="source", metavar="SOURCE",
                   help="Run this source instead of a file")
    p.add_argument("--no-repo", action="store_true",
                   help="Do not open a repository into `repo`")
    p.add_argument("args", nargs="*", metavar="ARGS",
                   help="Arguments for the script, as sys.argv[1:]")
    p.set_defaults(_handler="pyjj_cli.commands.python_repl:python_repl")
