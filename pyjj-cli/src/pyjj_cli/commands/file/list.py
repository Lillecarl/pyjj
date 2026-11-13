"""file subcommand: file_list."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
def file_list(args: argparse.Namespace) -> int:
    """`jj file list` — the paths a revision holds.

    jj renders each entry with `templates.file_list`, which prints the
    path and nothing else. `-T` replaces that; pyjj-cli's is a Jinja
    template, and `path` is what it has to work with.
    """
    with read_repo(args) as (settings, ws, repo):
        commit = _resolve_one(repo, settings, args.revision)
        template = _resolve_template(settings, ws, args, "file_list")
        paths = _cli_paths(ws, getattr(args, "filesets", None))
        _warn_unmatched_paths(ws, paths, [commit])
        for p in sorted(commit.list_files(paths or None)):
            print(template.render({"path": p}) if template is not None else p)
        return 0
