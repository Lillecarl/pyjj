from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("edit", help="Edit (check out) a specific revision")
    # jj takes the revision positionally or as `-r`, never both.
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("revision_pos", nargs="?", metavar="REVSETS",
                       help="The revision to edit")
    group.add_argument("-r", "--revision", dest="revision_flags",
                       metavar="REVSETS", help="The revision to edit")
    p.set_defaults(_handler="pyjj_cli.commands.rewrite.edit:edit")
