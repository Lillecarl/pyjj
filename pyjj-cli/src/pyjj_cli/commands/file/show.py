"""file subcommand: file_show."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _resolve_template,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
    _wc_commit,
)

def file_show(args) -> int:
    """`jj file show` — the content of the paths a revision holds.

    jj renders each file's metadata with `templates.file_show` before
    its content. That template is empty by default, so a plain run
    prints content alone; `-T` is how a caller asks for a header. The
    pyjj-cli spelling is a Jinja template over `path`.
    """
    try:
        settings, ws, repo = _load(args)
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

        for pattern in args.filesets:
            # Support exact paths and directory filtering via list_files
            paths = commit.list_files([pattern])
            if not paths:
                # Try as exact file
                try:
                    content = commit.read_file(pattern)
                    header(pattern)
                    sys.stdout.buffer.write(content)
                    if not content.endswith(b"\n"):
                        sys.stdout.buffer.write(b"\n")
                    continue
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
            for p in paths:
                try:
                    content = commit.read_file(p)
                    header(p)
                    sys.stdout.buffer.write(content)
                except pyjj.JjError as e:
                    print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
                    return 1
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
