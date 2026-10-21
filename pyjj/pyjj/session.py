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

**A failed block writes nothing but the snapshot.** Like every jj
command, a block first snapshots the working copy. The block's
operations then accumulate in one jj transaction, which becomes an
operation only when the block ends cleanly. An exception halfway through
leaves no half-applied change and no rollback entry in the operation
log. `Atomic.rolled_back` says which way a block ended.

Every reader has an `_async` sibling, and `atomic_async` is the block
for a coroutine. Its verbs are awaitables, and jj's work runs off the
event loop:

    repo = await pyjj.open_async()
    async with repo.atomic_async("tidy the stack") as tx:
        await tx.squash("@", into="@-")

Errors keep their class: a jj failure raises the `pyjj.JjError` subclass
jj gave, with notes that say what was asked and that nothing was
written. `PyjjError` is only for what this wrapper refuses itself.
"""

from __future__ import annotations

import functools
import os
import queue
import threading
import traceback
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Concatenate, Generic, ParamSpec, TypeVar

import anyio
import anyio.from_thread
import anyio.lowlevel
import anyio.to_thread
import pyjj_bindings as _bindings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Sequence
    from types import TracebackType

    from pyjj_bindings import (
        AbsorbStats,
        Commit,
        GraphNode,
        Transaction,
        UserSettings,
        Workspace,
    )

    Revisions = str | Sequence[str]
    Hunks = dict[str, Sequence[int]]


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _in_thread(fn: Callable[_P, _T]) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """`fn` as a coroutine that runs it in a worker thread. The bindings
    release the GIL while jj works, so the event loop keeps running."""

    @functools.wraps(fn)
    async def run(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        result: _T = await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
        return result

    run.__name__ = f"{fn.__name__}_async"
    run.__qualname__ = f"{fn.__qualname__}_async"
    return run


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
    except _bindings.JjError as e:
        e.add_note(f"no jj repository at {root}")
        raise
    settings = _bindings.UserSettings.for_repo(
        workspace.repo_path, workspace.workspace_root)
    # Reloaded under the full settings, the way the CLI does it.
    workspace = _bindings.Workspace.load(settings, root)
    return Repo(workspace, settings)


open_async = _in_thread(open)


class Repo:
    """A loaded repository, and the things worth asking it directly."""

    def __init__(self, workspace: Workspace, settings: UserSettings) -> None:
        self._workspace = workspace
        self._settings = settings
        self._repo = workspace.load_at_head()

    def __enter__(self) -> Repo:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def __repr__(self) -> str:
        return f"<pyjj.Repo {self.root}>"

    @property
    def root(self) -> str:
        return self._workspace.workspace_root

    @property
    def settings(self) -> UserSettings:
        """The `UserSettings` behind this repository, for the parts of
        `pyjj` this wrapper does not cover."""
        return self._settings

    @property
    def workspace(self) -> Workspace:
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

    def resolve(self, revision: str) -> Commit:
        """One commit, by any revset that names exactly one.

        A revset naming none or several is the caller's mistake, and
        jj's own message says which -- including the divergent-change
        case, where a change id names more than one commit.
        """
        try:
            return self._repo.resolve_single(self._settings, revision)
        except _bindings.JjError as e:
            e.add_note(f"revision {revision!r}")
            raise

    def revset(self, revision: str) -> list[Commit]:
        """Every commit a revset names, in jj's order."""
        try:
            return self._repo.revset(self._settings, revision)
        except _bindings.JjError as e:
            e.add_note(f"revset {revision!r}")
            raise

    def log(self, revision: str = "::@", limit: int | None = None) -> list[GraphNode]:
        """`jj log`'s rows: each commit with its edges to the ancestors
        the revset keeps."""
        return self._repo.log_graph(self._settings, revision, limit=limit)

    def conflicts(self) -> list[Commit]:
        """Every commit currently carrying a conflict."""
        return self.revset("conflicts()")

    @property
    def operation_id(self) -> str:
        return self._repo.operation.id

    reload_async = _in_thread(reload)
    snapshot_async = _in_thread(snapshot)
    resolve_async = _in_thread(resolve)
    revset_async = _in_thread(revset)
    log_async = _in_thread(log)
    conflicts_async = _in_thread(conflicts)

    @asynccontextmanager
    async def atomic_async(
        self,
        description: str = "pyjj",
        *,
        allow_conflicts: bool = False,
        allow_immutable: bool = False,
    ) -> AsyncIterator[AsyncAtomic]:
        """`atomic`, for a coroutine: the same block, all or nothing.

        A `Transaction` must stay on the thread that made it, so the
        whole block, from snapshot to commit, runs on one thread of its
        own. Each verb waits for that thread without blocking the loop.
        A cancelled verb finishes first; the block then discards.
        """
        pinned = _PinnedThread()
        block = self.atomic(description, allow_conflicts=allow_conflicts,
                            allow_immutable=allow_immutable)
        try:
            handle = AsyncAtomic(await pinned.call(block.__enter__), pinned)
            try:
                yield handle
            except BaseException as e:
                exit_with = functools.partial(block.__exit__, type(e), e, e.__traceback__)
                if not await pinned.call(exit_with, outer=e.__traceback__):
                    raise
            else:
                await pinned.call(functools.partial(block.__exit__, None, None, None))
            finally:
                # The handle holds the last reference to the transaction,
                # which must be freed on the thread that made it.
                await pinned.call(handle._release)
        finally:
            pinned.close()

    @contextmanager
    def atomic(
        self,
        description: str = "pyjj",
        *,
        allow_conflicts: bool = False,
        allow_immutable: bool = False,
    ) -> Iterator[Atomic]:
        """Everything in the block, or nothing.

        The working copy is snapshotted first, as every jj command does.
        The block's operations then accumulate in one jj transaction,
        which becomes an operation only on a clean exit. An exception
        before that writes nothing more: there is no half-applied state
        to undo, and no rollback entry in the operation log.

        `allow_immutable` lets the block rewrite commits
        `immutable_heads()` protects; without it the first such rewrite
        raises, as it does in jj. `allow_conflicts` keeps a result that
        introduced a conflict; without it the block is discarded and
        the conflicted commits are named.
        """
        self.snapshot()
        transaction = self._repo.start_transaction(self._settings)
        atomic = Atomic(self, transaction, allow_immutable=allow_immutable)
        old_wc_hex = self._repo.view()[self._workspace.workspace_name]
        try:
            yield atomic
            if not allow_conflicts:
                atomic._refuse_conflicts()
            # `Transaction.commit` refuses pending rewrites. This is
            # idempotent, so a verb that forgets it costs nothing.
            transaction.rebase_descendants()
            self._export_git_refs(transaction)
        except BaseException as e:
            # Deliberately broad: an unpredicted error is exactly when a
            # caller relies on the discard.
            atomic._discarded = True
            e.add_note(f"{description}: nothing was written; the block's "
                       "transaction was discarded.")
            raise
        transaction.commit(description)
        self.reload()
        try:
            self._checkout_if_moved(old_wc_hex)
        except BaseException as e:
            e.add_note(f"{description}: the operation was written, but the "
                       "working copy on disk was not updated. Run "
                       "`pyjj workspace update-stale`.")
            raise

    def _checkout_if_moved(self, old_wc_hex: str) -> None:
        """What the CLI does after every transaction: when the block
        moved the working-copy commit, write its tree out to disk.

        Without it a scripted `new(edit=True)` leaves the new commit
        empty on paper while the old files sit on disk, and the next
        snapshot absorbs them into it -- found the same blind session
        as the dropped restore write.
        """
        workspace_name = self._workspace.workspace_name
        new_wc_hex = self._repo.view()[workspace_name]
        if new_wc_hex == old_wc_hex:
            return
        fresh = _bindings.Workspace.load(self._settings,
                                         self._workspace.workspace_root)
        fresh_repo = fresh.load_at_head()
        fresh.check_out(
            fresh_repo,
            fresh_repo.get_commit(_bindings.CommitId(new_wc_hex)))

    def _export_git_refs(self, transaction: Transaction) -> None:
        """What the CLI's transaction-finish does: a colocated repo
        exports bookmarks/tags and resets HEAD on every transaction.

        Without it a scripted rewrite leaves `<name>@git` on the commit
        the bookmark moved away from -- found by a blind CTF solver
        whose single atomic block was otherwise perfect.
        """
        if not self._workspace.is_colocated():
            return
        transaction.git_reset_head(
            self._workspace.workspace_name, self._workspace.workspace_root)
        transaction.git_export_refs()


class Atomic:
    """The operations a block may perform.

    Each takes jj's own argument names, so `tx.squash("@", into="@-")`
    reads as `jj squash --from @ --into @-` does.
    """

    def __init__(self, repo: Repo, transaction: Transaction, *, allow_immutable: bool) -> None:
        self._repo = repo
        self._tx = transaction
        self._allow_immutable = allow_immutable
        self._touched: list[Commit] = []
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
    def transaction(self) -> Transaction:
        """The `Transaction`, for the parts of `pyjj` this does not
        cover. Anything done through it joins the same block."""
        return self._tx

    def _commit(self, revision: str | Commit) -> Commit:
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
        except _bindings.JjError as e:
            e.add_note(f"revision {revision!r}")
            raise
        if len(found) != 1:
            raise PyjjError(
                f"revision {revision!r} names {len(found)} commits; "
                "an operation needs exactly one")
        return self._repo._repo.get_commit(found[0])

    def _commits(self, revisions: Revisions) -> list[Commit]:
        if isinstance(revisions, str):
            revisions = [revisions]
        return [self._commit(revision) for revision in revisions]

    def _guard(self, commits: Sequence[Commit]) -> None:
        """jj's own refusal to rewrite shared history."""
        if self._allow_immutable:
            return
        self._tx.check_rewritable(self._repo.settings,
                                  [commit.id for commit in commits])

    def _record(self, *commits: Commit | None) -> None:
        self._touched.extend(commit for commit in commits if commit is not None)

    def _finish(self, *commits: Commit) -> None:
        """Rebase the block's descendants and record what a verb wrote.

        Every verb ends this way, so a later verb in the block sees
        rebased descendants and `Transaction.commit` finds no pending
        rewrites. Verbs
        that record nothing (`absorb` returns stats, not commits) or
        rebase nothing (`duplicate`, `abandon --restore-descendants`)
        call the pieces directly and stay visibly different.
        """
        self._tx.rebase_descendants()
        self._record(*commits)

    # ---- the operations -------------------------------------------------

    def describe(self, revision: str = "@", *, message: str) -> Commit:
        """`jj describe`: set a commit's description."""
        target = self._commit(revision)
        self._guard([target])
        builder = self._tx.rewrite_commit(self._repo.settings, target)
        builder.set_description(message)
        written = builder.write(self._repo._repo)
        self._finish(written)
        return written

    def new(self, parents: Revisions = "@", *,
            message: str | None = None, edit: bool = True) -> Commit:
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
            # `edit`, not `set_wc_commit`: it abandons the old working-copy
            # commit when that is empty and undescribed, as `jj new` does.
            self._tx.edit(self._repo.workspace.workspace_name, written)
        self._finish(written)
        return written

    def commit(self, *, message: str, revision: str = "@") -> Commit:
        """`jj commit`: describe the working-copy commit and start a
        new one on top, which is where the next edits land."""
        described = self.describe(revision, message=message)
        return self.new(described.id.hex(), edit=True)

    def squash(self, revision: str = "@", *, into: str | None = None,
               paths: Sequence[str] | None = None,
               hunks: Hunks | None = None, keep_emptied: bool = False) -> Commit:
        """`jj squash`: move a commit's changes into another.

        `into` defaults to the parent, as `jj squash` does. `paths`
        narrows it to a fileset; `hunks` to selected hunks of those
        files, the shape `pyjj.hunk` produces.
        """
        source = self._commit(revision)
        if into is not None:
            destination = self._commit(into)
        elif len(source.parent_ids) == 1:
            destination = self._repo._repo.get_commit(source.parent_ids[0])
        else:
            raise PyjjError(
                f"squash {revision!r}: it has {len(source.parent_ids)} "
                "parents, so name the destination with `into`.")
        self._guard([source, destination])
        builder = self._tx.squash(source, destination,
                                  list(paths) if paths else None,
                                  hunks, keep_emptied=keep_emptied)
        if builder is None:
            raise PyjjError(
                f"squash {revision!r} into "
                f"{into or 'its parent'!r}: nothing to move. "
                "The paths or hunks named no change.")
        written = builder.write(self._repo._repo)
        self._finish(written)
        return written

    def split(self, revision: str = "@", *,
              paths: Sequence[str] | None = None,
              hunks: Hunks | None = None,
              message: str | None = None,
              parallel: bool = False) -> tuple[Commit, Commit]:
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
        # The remainder rewrites `target`, so the rebase moves `@` onto it
        # only when `@` was `target`, as `jj split` does.
        self._finish(first, second)
        return first, second

    def rebase(self, revisions: Revisions, *,
               destination: Revisions | None = None,
               after: Revisions | None = None,
               before: Revisions | None = None,
               whole_branch: bool = False) -> list[Commit]:
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
        moving = set(ids)
        parents, children = [], []
        if destination is not None:
            parents = [c.id for c in self._commits(destination)]
        elif after is not None:
            anchors = self._commits(after)
            parents = [c.id for c in anchors]
            # Asked of the transaction: the block may have rewritten or
            # created children since it started.
            children = [
                child for child in self._tx.revset(
                    self._repo.settings,
                    " | ".join(f"{c.id.hex()}+" for c in anchors))
                if child not in moving]
        elif before is not None:
            anchors = self._commits(before)
            children = [c.id for c in anchors]
            parents = list(dict.fromkeys(
                parent for c in anchors for parent in c.parent_ids
                if parent not in moving))
        self._tx.move_commits(target_commit_ids=[] if whole_branch else ids,
                              target_root_ids=ids if whole_branch else [],
                              new_parent_ids=parents, new_child_ids=children)
        self._finish(*targets)
        return targets

    def abandon(self, revisions: Revisions, *,
                restore_descendants: bool = False) -> list[Commit]:
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
            self._tx.rebase_descendants()
        return targets

    def duplicate(self, revisions: Revisions) -> list[Commit]:
        """`jj duplicate`: copy commits, leaving the originals."""
        copies = self._tx.duplicate(self._commits(revisions))
        self._record(*copies)
        return copies

    def absorb(self, revision: str = "@", *,
               into: str | None = None,
               paths: Sequence[str] | None = None) -> AbsorbStats:
        """`jj absorb`: push each change back into the ancestor that
        last touched those lines.

        `into` narrows the candidates to a revset, as `jj absorb
        --into` does. Returns jj's own stats for what moved where.
        """
        source = self._commit(revision)
        stats = self._tx.absorb(self._repo.settings, source, into,
                                list(paths) if paths else None,
                                check_immutable=not self._allow_immutable)
        self._tx.rebase_descendants()
        return stats

    def restore(self, paths: Sequence[str] | None = None, *,
                into: str = "@", from_revision: str | None = None) -> Commit:
        """`jj restore`: take paths from one revision into another.

        `from_revision` defaults to the parent of `into`, as `jj
        restore` does, so `restore(["a.txt"])` undoes that file's
        changes in the working-copy commit.
        """
        target = self._commit(into)
        source = self._commit(from_revision) if from_revision is not None \
            else None
        self._guard([target])
        builder = self._tx.restore(source, target,
                                   list(paths) if paths else None)
        written = builder.write(self._repo._repo)
        self._finish(written)
        return written

    def revert(self, revisions: Revisions, *,
               destination: str = "@") -> list[Commit]:
        """`jj revert`: apply the reverse of commits as new commit(s).

        Each target becomes a chained child starting at `destination`,
        with jj's own revert description. Purely additive -- nothing
        existing is rewritten, so there is nothing to guard.
        """
        targets = self._commits(revisions)
        current = self._commit(destination)
        out = []
        for target in targets:
            builder = self._tx.revert_commit(target, [current.id])
            first = target.description.splitlines()[0] \
                if target.description else ""
            builder.set_description(
                f'Revert "{first}"\n\n'
                f"This reverts commit {target.id.hex()}.\n")
            current = builder.write(self._repo._repo)
            out.append(current)
        self._finish(*out)
        return out

    def bookmark(self, name: str, revision: str = "@") -> Commit:
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


@dataclass
class _Call(Generic[_T]):
    """One call handed to a `_PinnedThread`, and how it ended."""

    fn: Callable[[], _T] | None
    token: anyio.lowlevel.EventLoopToken
    outer: TracebackType | None
    done: anyio.Event = field(default_factory=anyio.Event)
    result: _T | None = None
    error: BaseException | None = None


class _PinnedThread:
    """One thread that runs every call it gets, in order.

    `anyio.to_thread` may pick a different thread per call, and a
    `Transaction` panics when another thread touches it.
    """

    def __init__(self) -> None:
        self._calls: queue.SimpleQueue[_Call[Any] | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="pyjj-atomic", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while (call := self._calls.get()) is not None:
            fn, call.fn = call.fn, None
            try:
                if fn is not None:
                    call.result = fn()
            except BaseException as e:  # noqa: BLE001 -- re-raised in `call`
                call.error = _without_own_frames(e, call.outer)
            # `fn` may hold the transaction; an error's traceback holds
            # the frame of `call`, so `call` must not.
            del fn
            anyio.from_thread.run_sync(call.done.set, token=call.token)

    async def call(self, fn: Callable[[], _T], *, outer: TracebackType | None = None) -> _T:
        """`fn()` on this thread. `outer` is the traceback an error passed
        in already had; frames this thread adds above it are cut."""
        call = _Call(fn, anyio.lowlevel.current_token(), outer)
        # An error's traceback holds this frame; `fn` may hold the
        # transaction, which the pinned thread alone may free.
        del fn
        self._calls.put(call)
        # The thread runs the call to its end whatever happens here, so
        # wait for it rather than leave the transaction mid-verb.
        with anyio.CancelScope(shield=True):
            await call.done.wait()
        if call.error is not None:
            raise call.error
        return call.result  # type: ignore[return-value]

    def close(self) -> None:
        self._calls.put(None)


def _without_own_frames(error: BaseException, outer: TracebackType | None) -> BaseException:
    """`error` with the frames this thread added cut, kept as a note.

    Those frames hold the transaction. Handed to the event loop, they
    would free it there, and pyo3 refuses to drop an unsendable object
    on another thread.
    """
    own: list[TracebackType] = []
    tb = error.__traceback__
    while tb is not None and tb is not outer:
        own.append(tb)
        tb = tb.tb_next
    if own:
        lines = traceback.format_list(traceback.extract_tb(own[0], limit=len(own)))
        error.add_note("On the block's thread:\n" + "".join(lines).rstrip())
    return error.with_traceback(outer)


def _on_pinned(
    verb: Callable[Concatenate[Atomic, _P], _T],
) -> Callable[Concatenate[AsyncAtomic, _P], Coroutine[Any, Any, _T]]:
    """An `Atomic` verb as an `AsyncAtomic` coroutine on the block's thread."""

    async def run(self: AsyncAtomic, /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        return await self._pinned.call(functools.partial(verb, self._block(), *args, **kwargs))

    run.__name__ = verb.__name__
    run.__qualname__ = f"AsyncAtomic.{verb.__name__}"
    run.__doc__ = verb.__doc__
    return run


class AsyncAtomic:
    """`Atomic`'s verbs as coroutines, for `Repo.atomic_async`."""

    def __init__(self, atomic: Atomic, pinned: _PinnedThread) -> None:
        self._atomic: Atomic | None = atomic
        self._pinned = pinned
        self._rolled_back = False

    def _block(self) -> Atomic:
        if self._atomic is None:
            raise PyjjError("the block has ended; its verbs are gone with it")
        return self._atomic

    def _release(self) -> None:
        if self._atomic is not None:
            self._rolled_back = self._atomic.rolled_back
            self._atomic = None

    @property
    def rolled_back(self) -> bool:
        """Whether the block ended by discarding its work."""
        return self._atomic.rolled_back if self._atomic is not None else self._rolled_back

    describe = _on_pinned(Atomic.describe)
    new = _on_pinned(Atomic.new)
    commit = _on_pinned(Atomic.commit)
    squash = _on_pinned(Atomic.squash)
    split = _on_pinned(Atomic.split)
    rebase = _on_pinned(Atomic.rebase)
    abandon = _on_pinned(Atomic.abandon)
    duplicate = _on_pinned(Atomic.duplicate)
    absorb = _on_pinned(Atomic.absorb)
    restore = _on_pinned(Atomic.restore)
    revert = _on_pinned(Atomic.revert)
    bookmark = _on_pinned(Atomic.bookmark)
