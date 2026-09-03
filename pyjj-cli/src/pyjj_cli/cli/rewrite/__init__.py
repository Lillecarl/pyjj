# cli/rewrite package — one module per subcommand, mirroring commands/rewrite/.
# Keeps each parser small and avoids the old 66-line/9-parser monolith.
from . import (abandon, absorb, duplicate, fix, rebase, restore, revert,
               simplify_parents, split, squash)


def add_parsers(sub) -> None:
    squash.register(sub)
    rebase.register(sub)
    absorb.register(sub)
    fix.register(sub)
    revert.register(sub)
    abandon.register(sub)
    duplicate.register(sub)
    restore.register(sub)
    split.register(sub)
    simplify_parents.register(sub)
