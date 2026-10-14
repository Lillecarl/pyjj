"""file subcommand: file_list."""

from ..common import (
    _resolve_template,
    _resolve_one,
    command,
    read_repo,
)

@command
def file_list(args) -> int:
    """`jj file list` — the paths a revision holds.

    jj renders each entry with `templates.file_list`, which prints the
    path and nothing else. `-T` replaces that; pyjj-cli's is a Jinja
    template, and `path` is what it has to work with.
    """
    with read_repo(args) as (settings, ws, repo):
        commit = _resolve_one(repo, settings, args.revision)
        template = _resolve_template(settings, ws, args, "file_list")
        paths = getattr(args, "filesets", None) or None
        for p in sorted(commit.list_files(paths)):
            print(template.render({"path": p}) if template is not None else p)
        return 0
