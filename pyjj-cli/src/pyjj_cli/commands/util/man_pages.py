"""util subcommand: install-man-pages — one roff page per command.

`jj util install-man-pages PATH` writes `PATH/man1/jj-<path>.1` per
subcommand with clap_mangen. This writes the same layout from pyjj-cli's
argparse tree.
"""
import sys
from pathlib import Path

from .markdown_help import (
    _children,
    _name,
    _positional,
    _subparsers,
    _visible,
    _walk,
)


def util_install_man_pages(args) -> int:
    from pyjj_cli.__main__ import GLOBAL_FLAGS_OUTSIDE_ARGPARSE, build_parser

    parser = build_parser()
    man1 = Path(args.path) / "man1"
    try:
        man1.mkdir(parents=True, exist_ok=True)
        for path, sub, about in _walk(parser, parser.prog,
                                      parser.description or ""):
            name = path.replace(" ", "-")
            extra = sorted(GLOBAL_FLAGS_OUTSIDE_ARGPARSE) if sub is parser else ()
            (man1 / f"{name}.1").write_text(_page(name, path, sub, about, extra))
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _esc(text) -> str:
    """roff-escape: a backslash and a hyphen are literal, and a leading
    `.` or `'` would start a request."""
    text = str(text or "").replace("\\", "\\e").replace("-", "\\-")
    return "\n".join("\\&" + line if line[:1] in (".", "'") else line
                     for line in text.splitlines())


def _bold(flag: str) -> str:
    return f"\\fB{_esc(flag)}\\fR"


def _page(name, path, parser, about, global_flags) -> str:
    positionals = [a for a in parser._actions
                   if not a.option_strings and _visible(a)]
    options = [a for a in parser._actions if a.option_strings and _visible(a)]
    subparsers = _subparsers(parser)

    synopsis = [_bold(path)]
    for action in options:
        synopsis.append("[" + "|".join(_bold(s) for s in action.option_strings) + "]")
    synopsis += [f"[{_bold(f)}]" for f in global_flags]
    synopsis += [f"\\fI{_esc(_positional(a))}\\fR" for a in positionals]
    if subparsers is not None:
        synopsis.append("<\\fIsubcommands\\fR>")

    out = [".TH {} 1\n".format(_esc(name)),
           ".SH NAME\n", f"{_esc(name)} \\- {_esc(about)}\n",
           ".SH SYNOPSIS\n", " ".join(synopsis) + "\n"]
    if about:
        out += [".SH DESCRIPTION\n", f"{_esc(about)}\n"]
    if options or positionals or global_flags:
        out.append(".SH OPTIONS\n")
        for action in options:
            label = ", ".join(_bold(s) for s in action.option_strings)
            if action.nargs != 0:
                label += f" \\fI<{_esc(_name(action))}>\\fR"
            out += [".TP\n", f"{label}\n", f"{_esc(_help(action))}\n"]
        for flag in global_flags:
            out += [".TP\n", f"{_bold(flag)}\n"]
        for action in positionals:
            out += [".TP\n", f"\\fI{_esc(_positional(action))}\\fR\n",
                    f"{_esc(_help(action))}\n"]
    if subparsers is not None:
        out.append(".SH SUBCOMMANDS\n")
        for child, _sub, help_ in _children(subparsers):
            out += [".TP\n", f"{_esc(path)}\\-{_esc(child)}(1)\n",
                    f"{_esc(help_)}\n"]
    return "".join(out)


def _help(action) -> str:
    text = (action.help or "").replace("%%", "%")
    if action.choices:
        text += "\n\nPossible values: " + ", ".join(map(str, action.choices))
    return text
