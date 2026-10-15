"""operation subcommand: next_commit."""

from ..common import (
    _next_prev,
    command,
)

@command
def next_commit(args) -> int:
    """`jj next [OFFSET]`: move the working copy forward.

    Without `--edit` the new working copy is a *child* of the commit
    `offset` steps ahead of `@`'s parent, and `@` itself is excluded from
    that walk -- so from a sibling branch `next` lands on the other line
    of development, not back on itself. With `--edit` the working copy
    becomes the descendant `offset` steps ahead of `@`.

    `--conflict` takes no offset (jj refuses the two together) and
    jumps to the nearest conflicted descendant instead, with the same
    edit/no-edit shape around it.
    """
    return _next_prev(
        args, "next", walk_dir="children",
        conflict_edit_rel="descendants",
        conflict_noedit_rel="other descendants",
        plain_edit_tpl="Error: No descendant found {offset} commit(s) "
                       "forward from the working copy",
        plain_noedit_tpl="Error: No other descendant found {offset} commit(s) "
                         "forward from the working copy parent(s)",
        noedit_from_parents=True)
