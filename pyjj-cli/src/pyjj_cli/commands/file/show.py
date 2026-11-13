"""file subcommand: file_show."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _cli_paths,
    _resolve_one,
    _resolve_template,
    _warn_unmatched_paths,
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command
def file_show(args: argparse.Namespace) -> int:
    """`jj file show` — the content of the paths a revision holds.

    jj renders each file's metadata with `templates.file_show` before
    its content. That template is empty by default, so a plain run
    prints content alone; `-T` is how a caller asks for a header. The
    pyjj-cli spelling is a Jinja template over `path`.
    """
    with read_repo(args) as (settings, ws, repo):
        commit = _resolve_one(repo, settings, args.revision)
        template = _resolve_template(settings, ws, args, "file_show")

        def header(path: str) -> None:
            # The content goes to the byte stream, so the header has to
            # as well: two streams over one file descriptor would print
            # every header after every file.
            if template is None:
                return
            text = template.render({"path": path}) + "\n"
            sys.stdout.flush()
            sys.stdout.buffer.write(text.encode("utf-8", "surrogateescape"))
            sys.stdout.buffer.flush()

        patterns = _cli_paths(ws, args.filesets)
        # jj warns and prints what did match, rather than failing.
        _warn_unmatched_paths(ws, patterns, [commit])
        for pattern in patterns:
            for p in commit.list_files([pattern]):
                try:
                    content = commit.read_file(p)
                    header(p)
                    sys.stdout.buffer.write(content)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
        return 0
