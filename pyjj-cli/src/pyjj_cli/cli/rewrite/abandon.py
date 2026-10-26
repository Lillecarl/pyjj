from __future__ import annotations

from typing import TYPE_CHECKING

from ..flags import Flag, add_flags

if TYPE_CHECKING:
    import argparse
def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                   help="Revisions to abandon (default: @)")
    # `-r` is an alias of the positional in jj. The two cannot share a
    # dest: an empty `nargs="*"` positional assigns its empty list last
    # and drops whatever `-r` appended, so `-r` gets its own name and
    # `abandon` joins the two (same shape as `show`).
    p.add_argument("-r", "--revision", dest="revision_flags",
                   action="append", metavar="REVISIONS",
                   help="Revisions to abandon")
    p.add_argument("--restore-descendants", dest="restore_descendants",
                   action="store_true", default=False,
                   help="Do not modify the content of the children of the abandoned commits")
    p.add_argument("--retain-bookmarks", dest="retain_bookmarks",
                   action="store_true", default=False,
                   help="Move bookmarks to the parent instead of deleting them")
    add_flags(p, [Flag.TRIAL])
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.abandon:abandon")
