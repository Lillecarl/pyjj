"""Fast-forward-only bookmarks: a published trunk moves forward only.

A name in `pyjj.fast-forward-bookmarks` (default jj's `trunk()`
candidates: `main`, `master`, `trunk`) is protected once it has a
remote counterpart on a remote other than `git`. Every colocated
bookmark has a `@git` mirror, so that one does not count, and a repo
that was never pushed stays unconstrained. A protected bookmark may be
created or moved to a descendant of where it was; moving it backwards
or sideways, deleting it, or leaving it conflicted is refused before
the transaction commits, so nothing is written.

The check reads the transaction's final view, so it catches every way
of moving the bookmark: `bookmark set --allow-backwards`, an abandon or
`--ignore-immutable` rewrite that drags it along, `undo`, `op restore`,
or a script's `tx.set_bookmark`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyjj_bindings

CONFIG_KEY = "pyjj.fast-forward-bookmarks"
DEFAULT_NAMES = ("main", "master", "trunk")


class NonFastForwardError(Exception):
    """A transaction would move a fast-forward-only bookmark otherwise."""

    def __init__(self, refused: list[tuple[str, str]]) -> None:
        self.refused = refused
        self.message = "\n".join(
            f"Refusing to {how} fast-forward-only bookmark {name}"
            for name, how in refused)
        super().__init__(self.message)


def protected_names(settings: pyjj_bindings.UserSettings,
                    base_repo: pyjj_bindings.ReadonlyRepo) -> list[str]:
    """The configured names that have a remote counterpart beside `@git`."""
    names = settings.get_string_list(CONFIG_KEY)
    if names is None:
        names = list(DEFAULT_NAMES)
    published = {rb.name for rb in base_repo.remote_bookmarks() if rb.remote != "git"}
    return [name for name in names if name in published]


def refusals(tx: pyjj_bindings.Transaction, base_repo: pyjj_bindings.ReadonlyRepo,
             settings: pyjj_bindings.UserSettings) -> list[tuple[str, str]]:
    """`(name, what the move does)` for each protected bookmark the
    transaction moves other than forward."""
    refused = []
    for name in protected_names(settings, base_repo):
        old = base_repo.get_bookmark(name)
        new = tx.get_bookmark(name)
        if old is None:
            continue
        if new is None or not new.target_ids:
            refused.append((name, "delete"))
            continue
        old_ids = sorted(i.hex() for i in old.target_ids)
        new_ids = sorted(i.hex() for i in new.target_ids)
        if old_ids == new_ids and old.has_conflict == new.has_conflict:
            continue
        if new.has_conflict:
            refused.append((name, "conflict"))
            continue
        target = new_ids[0]
        # The transaction's revset sees commits it wrote; the base's
        # would not.
        if not all(tx.revset(settings, f"{old_id} & ::{target}") for old_id in old_ids):
            refused.append((name, "move backwards or sideways"))
    return refused


def check(tx: pyjj_bindings.Transaction, base_repo: pyjj_bindings.ReadonlyRepo,
          settings: pyjj_bindings.UserSettings) -> None:
    """Raise `NonFastForwardError` if `tx` moves a protected bookmark
    other than forward."""
    refused = refusals(tx, base_repo, settings)
    if refused:
        raise NonFastForwardError(refused)
