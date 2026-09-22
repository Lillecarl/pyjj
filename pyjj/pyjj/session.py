"""The API an agent reaches for: open a repository, change it in a
block, and have the block be all-or-nothing.

`pyjj` proper mirrors jj_lib, so a caller assembles settings, loads a
workspace, opens a transaction, resolves revisions, and remembers to
call `rebase_descendants` before committing. That is the right shape
for a binding and the wrong shape for someone who wants to squash two
commits and move a third.

This module is the wrapper over it. The vocabulary is `jj`'s, because
an agent that knows the CLI should not have to learn a second set of
names: `revision`, `destination`, `into`, `after`, `before`,
`message`, `paths`.

    import pyjj

    with pyjj.open() as repo:
        with repo.atomic("tidy the stack") as tx:
            tx.squash("@", into="@-")
            tx.describe("@-", message="the whole change")

**A failed block writes nothing.** The operations accumulate in one jj
transaction, which becomes an operation only when the block ends
cleanly, so an exception halfway through leaves no trace -- not a
half-applied change, and not a rollback entry in the operation log
either. `Atomic.rolled_back` says which way a block ended.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pyjj_bindings as _bindings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class PyjjError(Exception):
    """Something this API refused, worded for the caller.

    Distinct from `pyjj.JjError`, which carries jj's own wording: this
    one names the argument that was wrong or the policy that refused.
    """


def open(path: str | None = None) -> Repo:
    """The repository at `path`, or the one containing the working
    directory.

    Settings carry the repo and workspace config layers, so
    `immutable_heads()` set with `jj config set --repo` means here what
    it means to `jj`.
    """
    root = path or os.getcwd()
    settings = _bindings.UserSettings()
    try:
        workspace = _bindings.Workspace.load(settings, root)
    except Exception as e:  # noqa: BLE001 -- reported, not swallowed
        raise PyjjError(
            f"no jj repository at {root}: {getattr(e, 'message', e)}"
        ) from e
    settings = _bindings.UserSettings.for_repo(
        workspace.repo_path, workspace.workspace_root)
    # Reloaded under the full settings, the way the CLI does it.
    workspace = _bindings.Workspace.load(settings, root)
    return Repo(workspace, settings)


class Repo:
    """A loaded repository, and the things worth asking it directly."""

    def __init__(self, workspace, settings) -> None:
        self._workspace = workspace
        self._settings = settings
        self._repo = workspace.load_at_head()

    def __enter__(self) -> Repo:
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def __repr__(self) -> str:
        return f"<pyjj.Repo {self.root}>"

    @property
    def root(self) -> str:
        return self._workspace.workspace_root

    @property
    def settings(self):
        """The `UserSettings` behind this repository, for the parts of
        `pyjj` this wrapper does not cover."""
        return self._settings

    @property
    def workspace(self):
        """The `Workspace`, likewise."""
        return self._workspace

    def reload(self) -> Repo:
        """Pick up whatever has been written since."""
        self._repo = self._workspace.load_at_head()
        return self

    def snapshot(self) -> Repo:
        """Take the working copy into the working-copy commit, the way
        every jj command does before it reads anything."""
        self._repo, _stats = self._workspace.snapshot(self._settings)
        return self

    def resolve(self, revision: str):
        """One commit, by any revset that names exactly one.

        A revset naming none or several is the caller's mistake, and
        jj's own message says which -- including the divergent-change
        case, where a change id names more than one commit.
        """
        try:
            return self._repo.resolve_single(self._settings, revision)
        except Exception as e:  # noqa: BLE001
            raise PyjjError(
                f"revision {revision!r}: {getattr(e, 'message', e)}") from e

    def revset(self, revision: str) -> list:
        """Every commit a revset names, in jj's order."""
        try:
            return self._repo.revset(self._settings, revision)
        except Exception as e:  # noqa: BLE001
            raise PyjjError(
                f"revset {revision!r}: {getattr(e, 'message', e)}") from e

    def log(self, revision: str = "::@", limit: int | None = None) -> list:
        """`jj log`'s rows: each commit with its edges to the ancestors
        the revset keeps."""
        return self._repo.log_graph(self._settings, revision, limit=limit)

    def conflicts(self) -> list:
        """Every commit currently carrying a conflict."""
        return self.revset("conflicts()")

    @property
    def operation_id(self) -> str:
        return self._repo.operation.id

    @contextmanager
    def atomic(
        self,
        description: str = "pyjj",
        *,
        allow_conflicts: bool = False,
        allow_immutable: bool = False,
    ) -> Iterator[Atomic]:
        """Everything in the block, or nothing.

        The block's operations accumulate in one jj transaction, which
        becomes an operation only on a clean exit. An exception writes
        nothing at all -- there is no half-applied state to undo, and
        no rollback entry in the operation log.

        `allow_immutable` lets the block rewrite commits
        `immutable_heads()` protects; without it the first such rewrite
        raises, as it does in jj. `allow_conflicts` keeps a result that
        introduced a conflict; without it the block is discarded and
        the conflicted commits are named.
        """
        self.snapshot()
        transaction = self._repo.start_transaction(self._settings)
        atomic = Atomic(self, transaction, allow_immutable=allow_immutable)
        try:
            yield atomic
            if not allow_conflicts:
                atomic._refuse_conflicts()
        except BaseException as e:
            # Deliberately broad. A rollback that only covered the
            # errors this module predicted would leave the repository
            # half-changed for the ones it did not, and an unpredicted
            # error is exactly when a caller is relying on this.
            atomic._discarded = True
            raise self._explain(e, description) from e
        # jj_lib asserts this before it will commit, and an assertion
        # inside a native extension takes the interpreter with it
        # rather than raising. It is idempotent, so the guard costs
        # nothing and a verb that forgets it cannot panic the caller.
        transaction.rebase_descendants(False)
        transaction.commit(description)
        self.reload()

    def _explain(self, error: BaseException, description: str):
        """The failure, said in a way the caller can act on."""
        if isinstance(error, (PyjjError, _bindings.JjError)):
            message = getattr(error, "message", str(error))
            return PyjjError(
                f"{description}: {message}\n"
                "Nothing was written: the block's transaction was "
                "discarded, so the repository is as it was.")
        return error


class Atomic:
    """The operations a block may perform.

    Each takes jj's own argument names, so `tx.squash("@", into="@-")`
    reads as `jj squash --from @ --into @-` does.
    """

    def __init__(self, repo: Repo, transaction, *, allow_immutable: bool) -> None:
        self._repo = repo
        self._tx = transaction
        self._allow_immutable = allow_immutable
        self._touched: list = []
        self._discarded = False
        # What was already conflicted, so the block is judged on what
        # it introduced rather than on what it inherited.
        self._conflicted_before = {
            commit_id.hex() for commit_id
            in transaction.revset(repo.settings, "conflicts()")}

    @property
    def rolled_back(self) -> bool:
        """Whether the block ended by discarding its work."""
        return self._discarded

    @property
    def transaction(self):
        """The `Transaction`, for the parts of `pyjj` this does not
        cover. Anything done through it joins the same block."""
        return self._tx

    def _commit(self, revision):
        """A revision argument, as a commit. Accepts a commit already.

        **Resolved against the transaction, not against the repository
        it started from.** A block's second operation names commits the
        first one moved, and `ReadonlyRepo.revset` still answers from
        the starting state -- so `squash` then `describe("@-")` rewrote
        a commit the squash had already replaced, and left the change
        divergent.
        """
        if not isinstance(revision, str):
            return revision
        try:
            found = self._tx.revset(self._repo.settings, revision)
        except Exception as e:  # noqa: BLE001
            raise PyjjError(
                f"revision {revision!r}: {getattr(e, 'message', e)}") from e
        if len(found) != 1:
            raise PyjjError(
                f"revision {revision!r} names {len(found)} commits; "
                "an operation needs exactly one")
        return self._repo._repo.get_commit(found[0])

    def _commits(self, revisions) -> list:
        if isinstance(revisions, str):
            revisions = [revisions]
        return [self._commit(revision) for revision in revisions]

    def _guard(self, commits) -> None:
        """jj's own refusal to rewrite shared history."""
        if self._allow_immutable:
            return
        self._tx.check_rewritable(self._repo.settings,
                                  [commit.id for commit in commits])

    def _record(self, *commits) -> None:
        self._touched.extend(commit for commit in commits if commit is not None)

    # ---- the operations -------------------------------------------------

    def describe(self, revision: str = "@", *, message: str):
        """`jj describe`: set a commit's description."""
        target = self._commit(revision)
        self._guard([target])
        builder = self._tx.rewrite_commit(self._repo.settings, target)
        builder.set_description(message)
        written = builder.write(self._repo._repo)
        self._tx.rebase_descendants(False)
        self._record(written)
        return written

    def new(self, parents: str | Sequence[str] = "@", *,
            message: str | None = None, edit: bool = True):
        """`jj new`: a commit on top of `parents`.

        `edit` moves the working copy onto it, which is what `jj new`
        does and what a following `commit()` expects.
        """
        on = self._commits(parents)
        builder = self._tx.new_commit(self._repo.settings,
                                      [commit.id for commit in on])
        if message is not None:
            builder.set_description(message)
        written = builder.write(self._repo._repo)
        if edit:
            self._tx.set_wc_commit(self._repo.workspace.workspace_name,
                                   written.id)
        self._tx.rebase_descendants(False)
        self._record(written)
        return written

    def commit(self, *, message: str, revision: str = "@"):
        """`jj commit`: describe the working-copy commit and start a
        new one on top, which is where the next edits land."""
        described = self.describe(revision, message=message)
        return self.new(described.id.hex(), edit=True)

    def squash(self, revision: str = "@", *, into: str | None = None,
               paths: Sequence[str] | None = None,
               hunks: dict | None = None, keep_emptied: bool = False):
        """`jj squash`: move a commit's changes into another.

        `into` defaults to the parent, as `jj squash` does. `paths`
        narrows it to a fileset; `hunks` to selected hunks of those
        files, the shape `pyjj.hunk` produces.
        """
        source = self._commit(revision)
        destination = self._commit(into) if into is not None else \
            self._repo._repo.get_commit(source.parent_ids[0])
        self._guard([source, destination])
        builder = self._tx.squash(source, destination,
                                  list(paths) if paths else None,
                                  hunks, keep_emptied)
        if builder is None:
            raise PyjjError(
                f"squash {revision!r} into "
                f"{into or 'its parent'!r}: nothing to move. "
                "The paths or hunks named no change.")
        written = builder.write(self._repo._repo)
        self._tx.rebase_descendants(False)
        self._record(written)
        return written

    def split(self, revision: str = "@", *,
              paths: Sequence[str] | None = None,
              hunks: dict | None = None,
              message: str | None = None,
              parallel: bool = False):
        """`jj split`: cut a commit in two.

        The named `paths`/`hunks` become the first commit and the rest
        the second. `parallel` makes them siblings rather than a line,
        as `jj split --parallel` does. Returns `(first, second)`.
        """
        target = self._commit(revision)
        self._guard([target])
        first_builder = self._tx.split_selected(
            target, list(paths) if paths else None, hunks)
        if first_builder is None:
            raise PyjjError(
                f"split {revision!r}: the paths or hunks named no change, "
                "so there is nothing to split off.")
        if message is not None:
            first_builder.set_description(message)
        first = first_builder.write(self._repo._repo)
        second_builder = (self._tx.split_remainder_parallel(target, first)
                          if parallel
                          else self._tx.split_remainder(target, first))
        second = second_builder.write(self._repo._repo)
        self._tx.set_wc_commit(self._repo.workspace.workspace_name, second.id)
        self._tx.rebase_descendants(False)
        self._record(first, second)
        return first, second

    def rebase(self, revisions: str | Sequence[str], *,
               destination: str | Sequence[str] | None = None,
               after: str | Sequence[str] | None = None,
               before: str | Sequence[str] | None = None,
               whole_branch: bool = False):
        """`jj rebase`: move commits onto new parents.

        `destination` sets the parents outright; `after`/`before`
        insert between existing commits, as `-A`/`-B` do. Exactly one
        of the three. `whole_branch` moves each named commit's whole
        branch (`-b`) rather than the commit alone (`-r`).
        """
        given = [name for name, value in
                 (("destination", destination), ("after", after),
                  ("before", before)) if value is not None]
        if len(given) != 1:
            raise PyjjError(
                "rebase takes exactly one of destination, after or before"
                + (f", got {', '.join(given)}" if given else ""))
        targets = self._commits(revisions)
        self._guard(targets)
        ids = [commit.id for commit in targets]
        parents, children = [], []
        if destination is not None:
            parents = [c.id for c in self._commits(destination)]
        elif after is not None:
            moved = self._commits(after)
            parents = [c.id for c in moved]
            children = [child.id for child in
                        self._repo.revset(
                            " | ".join(f"{c.id.hex()}+" for c in moved))]
        else:
            moved = self._commits(before)
            children = [c.id for c in moved]
            parents = [parent for c in moved for parent in c.parent_ids]
        self._tx.move_commits([] if whole_branch else ids,
                              ids if whole_branch else [],
                              parents, children)
        self._tx.rebase_descendants(False)
        self._record(*targets)
        return targets

    def abandon(self, revisions: str | Sequence[str], *,
                restore_descendants: bool = False):
        """`jj abandon`: drop commits, rebasing what sat on them.

        `restore_descendants` keeps the descendants' own trees rather
        than replaying them, which is `jj abandon --restore-descendants`.
        """
        targets = self._commits(revisions)
        self._guard(targets)
        if restore_descendants:
            self._tx.abandon_restoring_descendants(
                [commit.id for commit in targets])
        else:
            for commit in targets:
                self._tx.abandon_commit(commit)
            self._tx.rebase_descendants(False)
        return targets

    def duplicate(self, revisions: str | Sequence[str]):
        """`jj duplicate`: copy commits, leaving the originals."""
        copies = self._tx.duplicate(self._commits(revisions))
        self._record(*copies)
        return copies

    def bookmark(self, name: str, revision: str = "@"):
        """`jj bookmark set`: point a bookmark at a commit."""
        target = self._commit(revision)
        self._tx.set_bookmark(name, target.id)
        return target

    def _refuse_conflicts(self) -> None:
        """Conflicts this block introduced, asked of the transaction.

        Not of the commits the verbs returned: a rebase replaces them,
        so checking those ids inspects the versions from before the
        block and finds nothing. And not of the repository either --
        `conflicts()` there answers from the starting state.

        Conflicts that were already present are left alone; the block
        did not cause them and refusing them would make the wrapper
        unusable in a repository that has one.
        """
        now = {commit_id.hex() for commit_id
               in self._tx.revset(self._repo.settings, "conflicts()")}
        introduced = sorted(now - self._conflicted_before)
        if not introduced:
            return
        names = ", ".join(
            self._repo._repo.get_commit(_bindings.CommitId(hexed))
            .change_id.reverse_hex()[:12]
            for hexed in introduced[:4])
        raise PyjjError(
            f"the block left {names} in conflict. Pass "
            "allow_conflicts=True to keep a result that has one.")
