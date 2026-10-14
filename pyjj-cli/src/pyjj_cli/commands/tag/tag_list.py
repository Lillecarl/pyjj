"""tag subcommand: tag_list."""
import sys

import pyjj
from ..common import (
    CommandError,
    _ref_list_items,
    _sort_ref_items,
    _formatter,
    _print_ref,
    _resolve_template,
    _load,
)

def tag_list(args) -> int:
    """`jj tag list` — the bookmark listing, over tags.

    jj builds both from the same `collect_items`, so this reads the
    same helper with the other kind.
    """
    try:
        settings, ws, repo = _load(args)
        template = _resolve_template(settings, ws, args, "tag_list")
        items = _ref_list_items(repo, settings, args, "tag")
        _sort_ref_items(repo, settings, items, args, "tag")
        with _formatter(settings) as fmt:
            for tag, tracked in items:
                _print_ref(repo, settings, tag, template, tracked,
                           kind="tag", fmt=fmt)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
