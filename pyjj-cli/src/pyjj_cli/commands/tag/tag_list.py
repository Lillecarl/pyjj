"""tag subcommand: tag_list."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyjj

from ..common import (
    _formatter,
    _print_ref,
    _ref_list_items,
    _resolve_template,
    _sort_ref_items,
    command,
    read_repo,
)

if TYPE_CHECKING:
    import argparse

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def tag_list(args: argparse.Namespace) -> int:
    """`jj tag list` — the bookmark listing, over tags.

    jj builds both from the same `collect_items`, so this reads the
    same helper with the other kind.
    """
    with read_repo(args) as (settings, ws, repo):
        template = _resolve_template(settings, ws, args, "tag_list")
        items = _ref_list_items(repo, settings, args, "tag")
        _sort_ref_items(repo, settings, items, args, "tag")
        with _formatter(settings) as fmt:
            for tag, tracked in items:
                _print_ref(repo, settings, tag, template, tracked,
                           kind="tag", fmt=fmt)
        return 0
