"""util subcommand: markdown-help — the whole CLI as one Markdown page.

The layout is clap-markdown's, which `jj util markdown-help` prints:
one `##` section per command, then `###### **Subcommands:**`,
`**Arguments:**` and `**Options:**` lists. The content is pyjj-cli's own
argparse tree, so `cli_surface` can read either tool's page.
"""

from __future__ import annotations

import argparse
import sys

_FOOTER = """<hr/>

<small><i>
    This document was generated automatically by
    <a href="https://crates.io/crates/clap-markdown"><code>clap-markdown</code></a>.
</i></small>
"""


def util_markdown_help(args: argparse.Namespace) -> int:
    from pyjj_cli.__main__ import GLOBAL_FLAGS_OUTSIDE_ARGPARSE, build_parser

    sys.stdout.write(render(build_parser(), sorted(GLOBAL_FLAGS_OUTSIDE_ARGPARSE)))
    return 0


def render(parser: argparse.ArgumentParser, global_flags=()) -> str:
    commands = list(_walk(parser, parser.prog, parser.description or ""))
    out = [f"# Command-Line Help for `{parser.prog}`\n\n",
           f"This document contains the help content for the "
           f"`{parser.prog}` command-line program.\n\n",
           "**Command Overview:**\n\n"]
    for path, _sub, _about in commands:
        out.append(f"* [`{path}`↴](#{path.replace(' ', '-')})\n")
    out.append("\n")
    for path, sub, about in commands:
        extra = global_flags if sub is parser else ()
        out.append(_section(path, sub, about, extra))
    out.append(_FOOTER)
    return "".join(out)


def _walk(parser: argparse.ArgumentParser, path, about):
    yield path, parser, about
    subparsers = _subparsers(parser)
    if subparsers is None:
        return
    for name, sub, help_ in _children(subparsers):
        yield from _walk(sub, f"{path} {name}", help_)


def _subparsers(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _children(action):
    """`(name, parser, help)` per visible subcommand, sorted by name. An
    alias shares its parser, and argparse lists the canonical name first."""
    helps = {a.dest: a.help for a in action._choices_actions}
    seen = set()
    children = []
    for name, sub in action.choices.items():
        if id(sub) in seen:
            continue
        seen.add(id(sub))
        help_ = helps.get(name) or ""
        if help_ == argparse.SUPPRESS:
            continue
        children.append((name, sub, help_))
    return sorted(children, key=lambda child: child[0])


def _visible(action) -> bool:
    return (action.help != argparse.SUPPRESS
            and not isinstance(action, (argparse._HelpAction,
                                        argparse._SubParsersAction)))


def _section(path, parser: argparse.ArgumentParser, about, global_flags) -> str:
    positionals = [a for a in parser._actions
                   if not a.option_strings and _visible(a)]
    options = [a for a in parser._actions if a.option_strings and _visible(a)]
    subparsers = _subparsers(parser)

    usage = [path]
    if options or global_flags:
        usage.append("[OPTIONS]")
    usage += [_positional(a) for a in positionals]
    if subparsers is not None:
        usage.append("<COMMAND>" if subparsers.required else "[COMMAND]")

    out = [f"## `{path}`\n\n"]
    if about:
        out.append(f"{_text(about)}\n\n")
    out.append(f"**Usage:** `{' '.join(usage)}`\n\n")
    if subparsers is not None:
        out.append("###### **Subcommands:**\n\n")
        for name, _sub, help_ in _children(subparsers):
            out.append(_item(f"`{name}`", help_))
        out.append("\n")
    if positionals:
        out.append("###### **Arguments:**\n\n")
        for action in positionals:
            out.append(_item(f"`{_positional(action)}`", action.help,
                             action.choices))
        out.append("\n")
    if options or global_flags:
        out.append("###### **Options:**\n\n")
        for action in options:
            out.append(_item(_option(action), action.help, action.choices))
        for flag in global_flags:
            out.append(_item(f"`{flag}`", None))
        out.append("\n")
    out.append("\n\n")
    return "".join(out)


def _name(action) -> str:
    metavar = action.metavar
    if isinstance(metavar, tuple):
        metavar = metavar[0]
    return (metavar or action.dest).upper()


def _positional(action) -> str:
    name = _name(action)
    return {None: f"<{name}>", "?": f"[{name}]", "*": f"[{name}]...",
            "+": f"<{name}>...",
            argparse.REMAINDER: f"[{name}]..."}.get(action.nargs, f"<{name}>")


def _option(action) -> str:
    spellings = [f"`{s}`" for s in action.option_strings]
    if action.nargs != 0:
        spellings[-1] = spellings[-1][:-1] + f" <{_name(action)}>`"
    return ", ".join(spellings)


def _text(help_) -> str:
    return (help_ or "").replace("%%", "%")


def _item(label: str, help_, choices=None) -> str:
    text = _text(help_)
    line = f"* {label} — {text}\n" if text else f"* {label}\n"
    if choices:
        values = ", ".join(f"`{c}`" for c in choices)
        line += f"\n  Possible values: {values}\n\n"
    return line
