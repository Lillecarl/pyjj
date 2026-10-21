from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
def register(git_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = git_sub.add_parser("root", help="Show the underlying Git directory")
    p.set_defaults(_handler="pyjj_cli.commands.git.root:git_root")
