"""file subcommand: file_search."""
import fnmatch
import re
import sys

import pyjj
from ..common import (
    CommandError,
    _load,
    _resolve_one,
)

# What `--pattern` means when it names no kind. jj reads the pattern as
# `kind:pattern`, and a bare pattern as a regular expression.
_DEFAULT_KIND = "regex"

#: The characters that make a glob a glob rather than a name.
_GLOB_CHARS = "*?["


def file_search(args) -> int:
    """`jj file search` — the lines whose content matches a pattern.

    jj matches a line at a time, so an anchored pattern can name a whole
    line, and a glob has to match one end to end. Each matching line
    prints as `path:line` (`path:lineno:line` under `-n`), and
    `--name-only` prints each matching file once, by name.
    """
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        matches = _line_matcher(getattr(args, "pattern", "") or "")
        paths = getattr(args, "filesets", None) or None
        name_only = getattr(args, "name_only", False)
        line_number = getattr(args, "line_number", False)
        for path in sorted(commit.list_files(paths)):
            for content in _searchable_contents(repo, commit, path):
                if name_only:
                    if any(matches(line) for line in _lines(content)):
                        print(path)
                        break
                else:
                    _print_matches(path, content, matches, line_number)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1


def _searchable_contents(repo, commit, path):
    """The blobs `jj file search` looks through at `path`.

    A plain file reads directly. A file conflict searches each added
    side (the base is a remove, which jj does not print); anything else
    unreadable -- symlink, submodule, directory conflict -- is passed
    over rather than failing the command.
    """
    try:
        return [commit.read_file(path)]
    except pyjj.JjError:
        pass
    try:
        sides = commit.conflict_sides(path)
    except pyjj.JjError:
        return []
    return [sides["left"], sides["right"]]


def _print_matches(path, content, matches, line_number):
    """Each matching line as `path:line`, numbered under `-n`.

    Lines keep whatever newline they carry, and a last line without
    one still ends the row -- the same shape jj's own `write_matches`
    writes.
    """
    for number, line in enumerate(content.split(b"\n"), 1):
        if not matches(line):
            continue
        head = f"{path}:{number}:" if line_number else f"{path}:"
        # One write through the binary buffer: mixing `print` with
        # `sys.stdout.buffer` can reorder the two buffered layers.
        sys.stdout.buffer.write(head.encode() + line + b"\n")


def _lines(content: bytes):
    """The lines of `content`, the way jj splits them.

    Only `\n` separates a line, and a file ending in one carries no
    empty line after it. An empty file has no lines at all, which is
    what makes `exact:""` match a blank line and not an empty file.
    """
    lines = content.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def _line_matcher(pattern: str):
    """One line's worth of jj's string-pattern matching.

    The kinds are jj's own: `exact`, `substring`, `glob` and `regex`,
    each with an `-i` spelling that ignores case. A `glob` with no glob
    character in it is an exact match, which is jj's own shortcut.
    """
    kind = _DEFAULT_KIND
    if ":" in pattern:
        kind, pattern = pattern.split(":", 1)
    if kind in ("glob", "glob-i") and not any(c in pattern for c in _GLOB_CHARS):
        kind = "exact" if kind == "glob" else "exact-i"

    needle = pattern.encode("utf-8", "surrogateescape")
    folded = pattern.casefold()

    def decoded(line: bytes) -> str:
        return line.decode("utf-8", "surrogateescape")

    if kind == "exact":
        return lambda line: line == needle
    if kind == "exact-i":
        return lambda line: decoded(line).casefold() == folded
    if kind == "substring":
        return lambda line: needle in line
    if kind == "substring-i":
        return lambda line: folded in decoded(line).casefold()
    if kind in ("glob", "glob-i"):
        # A glob names the whole line, so `--pattern 'glob:*foo*'` is
        # what finds a word inside one.
        text = pattern.casefold() if kind == "glob-i" else pattern
        return lambda line: fnmatch.fnmatchcase(
            decoded(line).casefold() if kind == "glob-i" else decoded(line), text)
    if kind in ("regex", "regex-i"):
        try:
            expression = re.compile(
                needle, re.IGNORECASE if kind == "regex-i" else 0)
        except re.error as error:
            raise CommandError(f"Invalid pattern: {error}") from error
        return lambda line: expression.search(line) is not None
    raise CommandError(f"Invalid string pattern kind: {kind}:")
