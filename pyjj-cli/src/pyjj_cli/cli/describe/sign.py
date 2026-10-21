from __future__ import annotations

from typing import TYPE_CHECKING

from ..flags import Flag, add_flags

if TYPE_CHECKING:
    import argparse


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("sign", help="Cryptographically sign a revision")
    add_flags(p, [Flag.REVISION_APPEND, Flag.KEY])
    p.set_defaults(_handler="pyjj_cli.commands.crypto.sign:sign")
