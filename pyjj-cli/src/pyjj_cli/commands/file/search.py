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
    """`jj file search` — the files whose content matches a pattern.

    jj matches a line at a time, so an anchored pattern can name a whole
    line, and a glob has to match one end to end. A file that matches is
    printed once, by name: the command says which files carry the
    pattern, not where in them it sits.
    """
    try:
        settings, _ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        matches = _line_matcher(getattr(args, "pattern", "") or "")
        paths = getattr(args, "filesets", None) or None
        for path in sorted(commit.list_files(paths)):
            try:
                content = commit.read_file(path)
            except pyjj.JjError:
                # A symlink or a submodule has no content to search, and
                # jj passes over both rather than failing the command.
                continue
            if any(matches(line) for line in _lines(content)):
                print(path)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1


def _lines(content: bytes):
    """The lines of `content`, the way jj splits them.

    Only `\\n` separates a line, and a file ending in one carries no
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
