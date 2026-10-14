"""util subcommand: diff."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _color_words_rows,
    _compare_mode,
    _diff_formats,
    _render_diff,
    _unified_hunk_lines,
    settings_for,
    use_color,
)

def util_diff(args) -> int:
    """`jj util diff` -- compare two files on disk.

    The two paths render like one modified file: `--git` prints the
    `diff --git` header with the paths as given and unified hunks (no
    index/mode lines, which need a repository), and the default
    color-words format prints `Modified <after> (<before> =>
    <after>):`. Anything else (a short listing format, an external
    `--tool`) prints nothing -- verified against real jj, which never
    even invokes the tool here and exits 0 silently (unlike in-repo
    `jj diff`, which runs it and reports `Failed to generate diff`).
    Identical files print nothing at all.

    Like jj's own command this never touches the repository: no
    snapshot, no workspace needed, so `settings_for` (not `_load`)
    builds the settings.
    """
    try:
        settings = settings_for(args)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    before_path = args.path1
    after_path = args.path2
    try:
        before = Path(before_path).read_bytes()
    except OSError as e:
        print(f"Error: Cannot access {before_path}\n"
              f"Caused by: {e.strerror} (os error {e.errno})",
              file=sys.stderr)
        return 1
    try:
        after = Path(after_path).read_bytes()
    except OSError as e:
        print(f"Error: Cannot access {after_path}\n"
              f"Caused by: {e.strerror} (os error {e.errno})",
              file=sys.stderr)
        return 1
    # Formats first: jj errors on a bad `--tool` or conflicting flags
    # even when the files are identical, and only then takes the
    # identical-files early return.
    try:
        _short, long = _diff_formats(args)
    except CommandError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1
    if before == after:
        return 0
    if long not in ("git", "color_words"):
        return 0
    context = getattr(args, "context", None)
    context = 3 if context is None else context
    compare = _compare_mode(args)
    coloured = use_color(settings)
    if long == "git":
        lines = [
            [(f"diff --git a/{before_path} b/{after_path}", "file_header")],
            [(f"--- {before_path}", "file_header")],
            [(f"+++ {after_path}", "file_header")],
        ]
        lines += _unified_hunk_lines(before, after, context, compare)
        out = _render_diff(lines, coloured)
    else:
        if before_path != after_path:
            header = f"Modified {after_path} ({before_path} => {after_path}):"
        else:
            header = f"Modified {after_path}:"
        lines = [[(header, "header")]]
        lines += _color_words_rows(before, after, context, coloured, compare)
        out = _render_diff(lines, coloured, "diff color_words")
    sys.stdout.flush()
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    return 0
