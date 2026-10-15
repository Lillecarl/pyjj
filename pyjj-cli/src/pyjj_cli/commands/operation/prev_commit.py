"""operation subcommand: prev_commit."""

from ..common import (
    _next_prev,
    command,
)

@command
def prev_commit(args) -> int:
    """`jj prev [OFFSET]`: move the working copy backward.

    Without `--edit` the new working copy is a *child* of the ancestor
    `offset` steps behind `@`'s parent -- one more step back than
    `--edit` takes, because the new commit then sits where `@` used to
    relative to that ancestor. With `--edit` the working copy becomes the
    ancestor `offset` steps behind `@`.

    `--conflict` takes no offset (jj refuses the two together) and
    jumps to the nearest conflicted ancestor instead, with the same
    edit/no-edit shape around it.
    """
    return _next_prev(
        args, "prev", walk_dir="parents",
        conflict_edit_rel="ancestors",
        conflict_noedit_rel="ancestors",
        plain_edit_tpl="Error: No ancestor found {offset} commit(s) back "
                       "from the working copy",
        plain_noedit_tpl="Error: No ancestor found {offset} commit(s) back "
                         "from the working copy",
        noedit_from_parents=False)
