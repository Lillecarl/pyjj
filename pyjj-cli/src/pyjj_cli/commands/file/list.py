"""file subcommand: file_list."""
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

def file_list(args) -> int:
    """`jj file list` — the paths a revision holds.

    jj renders each entry with `templates.file_list`, which prints the
    path and nothing else. `-T` replaces that; pyjj-cli's is a Jinja
    template, and `path` is what it has to work with.
    """
    try:
        settings, ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        template = _resolve_template(settings, ws, args, "file_list")
        paths = getattr(args, "filesets", None) or None
        for p in sorted(commit.list_files(paths)):
            print(template.render({"path": p}) if template is not None else p)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
