"""Read both CLIs' argument surfaces and compare them.

`jj util markdown-help` prints the whole clap tree -- every subcommand,
every flag, every alias -- in one pass. That is the authoritative list,
straight from the binary, so it never drifts from the jj being tested.
pyjj-cli's surface comes from its own `argparse` tree.

The markdown is parsed with `markdown-it-py`, so the structure
(headings, list items, inline code) comes from a real CommonMark parser
rather than from line matching. Only the parts that are jj's own
convention are interpreted here: a level-2 heading whose text is a code
span names a subcommand, and a list item under "Options" starts with one
code span per flag spelling.

The comparison is coverage measurement, not parity: it says which argv
`jj` accepts and pyjj-cli does not, which is a different question from
whether the two behave the same on the argv both accept. The parity
suite answers the second question, and can only ask it about argv
pyjj-cli parses at all.

Hidden commands are absent by construction: clap leaves them out of
`markdown-help`, the same way it leaves them out of `--help`. So `bench`
and `debug` show up as pyjj-only here, and that is not a divergence.

One known under-report: `markdown-help` prints only an option's long
aliases, so a short alias like `jj rebase -d` (for `--destination`) does
not appear. The list is therefore a lower bound on jj's surface. It is
still authoritative for what it does list, which is what the baselines
and the coverage checklist are measured against.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess

from markdown_it import MarkdownIt

from cli_surface_excluded import (EXCLUDED_COMMANDS, EXCLUDED_FLAGS,
                                  excluded_flags)

# jj writes the help text after an em dash, and the alias list before it.
_EM_DASH = "—"


# jj lists an option's other spellings in a trailing bracket, and writes
# it two ways: `[alias: `destination`]` beside an option, and
# `[aliases: -r]` after the description of a positional. Both are jj's
# own convention, not markdown, which is why they are read from the text
# the parser hands back rather than by re-parsing the document.
# `alias(?:es)?`, not `aliases?`: the latter binds the `?` to the final
# `s` alone, so it matches "aliase" and never "alias".
_ALIAS_BRACKET = re.compile(r"\[alias(?:es)?:\s*([^\]]+)\]")


def _spelling(word: str) -> str | None:
    """One alias token as the flag jj would accept for it.

    jj writes short aliases with their dash (`-r`) and long ones without
    (`destination`), and wraps them in backticks in some sections but
    not others.
    """
    word = word.strip().strip("`,")
    if not word:
        return None
    if word.startswith("-"):
        return word
    return f"--{word}"


def _flags_from_item(token) -> set[str]:
    """Every flag spelling a single list item declares.

    An Options item reads `` `-r`, `--revision <REVSET>` [alias:
    `revisions`] — help ``: the code spans up to the em dash are the
    flags, and the bracket adds more spellings.

    An Arguments item reads ``` `<REVSETS>` — The revision(s)... [aliases:
    -r] ```. The positional itself is not a flag, but the bracket still
    is: `jj describe -r` and `jj metaedit -r` exist only this way, which
    is why the Arguments sections have to be read too.

    Some options are spelled as one token, `--branch/-b`, so a single
    code span can carry more than one flag.
    """
    flags: set[str] = set()
    for child in token.children or []:
        if child.type == "text" and _EM_DASH in child.content:
            break
        if child.type != "code_inline":
            continue
        for word in child.content.replace("/", " ").split():
            if word.startswith("-"):
                flags.add(word)
    for bracket in _ALIAS_BRACKET.findall(token.content):
        for word in bracket.split(","):
            spelling = _spelling(word)
            if spelling:
                flags.add(spelling)
    return flags


def jj_surface(jj_bin: str | None = None) -> dict[str, set[str]]:
    """{subcommand path: {every flag spelling it accepts}}.

    The root command is the empty string. Aliases count as spellings,
    because jj accepts them and so must pyjj-cli.
    """
    jj_bin = jj_bin or os.environ.get("PYJJ_PARITY_JJ") or "jj"
    out = subprocess.run(
        [jj_bin, "--no-pager", "util", "markdown-help"],
        capture_output=True, text=True, check=True,
    ).stdout
    tokens = MarkdownIt().parse(out)

    surface: dict[str, set[str]] = {}
    current: str | None = None
    heading_level: str | None = None
    in_list_item = False
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            heading_level = token.tag
            continue
        if token.type == "list_item_open":
            in_list_item = True
            continue
        if token.type == "list_item_close":
            in_list_item = False
            continue
        if token.type != "inline":
            continue

        if heading_level == "h2":
            # `## `jj bookmark set`` -- the whole path in one code span.
            heading_level = None
            text = token.content.strip()
            if text.startswith("`jj") and text.endswith("`"):
                current = text[1:-1].removeprefix("jj").strip()
                surface.setdefault(current, set())
            continue
        heading_level = None

        # Only the first paragraph of a list item declares flags; the
        # indented prose that follows is a paragraph of its own.
        if in_list_item and current is not None:
            previous = tokens[index - 1]
            if previous.type == "paragraph_open" and index >= 2 \
                    and tokens[index - 2].type == "list_item_open":
                surface[current] |= _flags_from_item(token)
    return surface


def pyjj_surface() -> dict[str, set[str]]:
    """The same shape, walked out of pyjj-cli's own `argparse` tree."""
    from pyjj_cli.__main__ import GLOBAL_FLAGS_OUTSIDE_ARGPARSE, build_parser

    surface: dict[str, set[str]] = {}

    def walk(parser: argparse.ArgumentParser, path: str) -> None:
        flags: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    walk(sub, f"{path} {name}".strip())
                continue
            flags |= set(action.option_strings)
        surface[path] = flags

    walk(build_parser(), "")
    # jj takes its global options on either side of the subcommand, which
    # argparse cannot express, so pyjj-cli strips or hoists those out of
    # argv before parsing. They are real, accepted flags; the parser tree
    # just never sees them.
    surface[""] |= set(GLOBAL_FLAGS_OUTSIDE_ARGPARSE)
    return surface


def compare(jj_bin: str | None = None) -> dict[str, object]:
    """What pyjj-cli is missing, per subcommand.

    `missing_commands` are subcommands jj has and pyjj-cli does not.
    `missing_flags` are flags on a subcommand both have. Anything
    pyjj-cli has and jj does not is reported too: those are pyjj's own
    commands (`hunk`, `templates`), jj's hidden ones, plus any
    accidental divergence.
    """
    jj = jj_surface(jj_bin)
    py = pyjj_surface()
    # Both parsers generate `--help`, so it says nothing about coverage.
    ignore = {"-h", "--help"}
    missing_flags = {}
    for name in sorted(set(jj) & set(py)):
        gap = (jj[name] - py[name]) - ignore - excluded_flags(name)
        if gap:
            missing_flags[name] = sorted(gap)
    return {
        "missing_commands": sorted(set(jj) - set(py) - set(EXCLUDED_COMMANDS)),
        "extra_commands": sorted(set(py) - set(jj)),
        "missing_flags": missing_flags,
    }


def checklist(jj_bin: str | None = None) -> dict[str, set[str]]:
    """Everything a test could claim: jj's surface, minus the exclusions.

    `{subcommand: {flag spellings}}`. A subcommand with no flags still
    appears, with an empty set, because the subcommand itself is an item
    to check off.
    """
    jj = jj_surface(jj_bin)
    return {
        name: (flags - {"-h", "--help"}) - excluded_flags(name)
        for name, flags in jj.items()
        if name not in EXCLUDED_COMMANDS
    }


def unclaimed(covered: dict[str, set[str]],
              jj_bin: str | None = None) -> dict[str, list[str]]:
    """What the checklist holds that no test has claimed.

    A subcommand appears under the key `"<name>"` with `"(command)"` in
    its list when the subcommand itself is unclaimed, so an entry always
    reads as the thing that needs a test.
    """
    result: dict[str, list[str]] = {}
    for name, flags in checklist(jj_bin).items():
        claimed = covered.get(name)
        missing = sorted(flags - (claimed or set()))
        if claimed is None:
            missing.insert(0, "(command)")
        if missing:
            result[name] = missing
    return result


def stale_claims(covered: dict[str, set[str]],
                 jj_bin: str | None = None) -> list[str]:
    """Claims that name something jj does not have, or something
    excluded. A mark for a flag jj dropped is a mark that checks off
    nothing, and it would quietly shrink the ledger."""
    jj = jj_surface(jj_bin)
    stale = []
    for name, flags in covered.items():
        if name not in jj:
            stale.append(f"jj {name} (no such subcommand)")
            continue
        if name in EXCLUDED_COMMANDS:
            stale.append(f"jj {name} (excluded)")
            continue
        for flag in sorted(flags):
            if flag not in jj[name]:
                stale.append(f"jj {name} {flag} (no such flag)")
            elif flag in excluded_flags(name):
                stale.append(f"jj {name} {flag} (excluded)")
    return sorted(stale)


def stale_exclusions(jj_bin: str | None = None) -> list[str]:
    """Exclusions that no longer name anything jj has.

    An exclusion outlives the flag it excuses if nobody checks, and then
    the ledger quietly under-reports. Every entry has to keep pointing at
    something real.
    """
    jj = jj_surface(jj_bin)
    stale = []
    for command in EXCLUDED_COMMANDS:
        if command not in jj:
            stale.append(f"jj {command}")
    for command, flags in EXCLUDED_FLAGS.items():
        if command not in jj:
            stale.append(f"jj {command} (whole command)")
            continue
        for flag in flags:
            if flag not in jj[command]:
                stale.append(f"jj {command} {flag}")
    return sorted(stale)


def report(jj_bin: str | None = None) -> str:
    jj = jj_surface(jj_bin)
    result = compare(jj_bin)
    missing_flag_count = sum(len(v) for v in result["missing_flags"].values())
    lines = [
        f"jj has {len(jj)} subcommands and "
        f"{sum(len(v) for v in jj.values())} flags.",
        f"pyjj-cli is missing {len(result['missing_commands'])} subcommands "
        f"and {missing_flag_count} flags on the ones it has.",
    ]
    if result["missing_commands"]:
        lines.append("\nSubcommands jj has and pyjj-cli does not:")
        lines += [f"  jj {name}" for name in result["missing_commands"]]
    if result["missing_flags"]:
        lines.append("\nFlags missing, by subcommand:")
        for name, flags in result["missing_flags"].items():
            lines.append(f"  jj {name}: {' '.join(flags)}")
    if result["extra_commands"]:
        lines.append("\nSubcommands pyjj-cli has and jj does not:")
        lines += [f"  pyjj {name}" for name in result["extra_commands"]]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
