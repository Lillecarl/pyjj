"""App-wide state: the loaded workspace/repo/settings, plus the mutation
entry point every widget must go through.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio.to_thread
import pyjj

from . import config as pyjjui_config


@dataclass
class AppState:
    workspace: pyjj.Workspace
    settings: pyjj.UserSettings
    repo: pyjj.ReadonlyRepo
    revset: str
    _skipped_confirmations: set[str] = field(
        default_factory=pyjjui_config.load_skipped_confirmations
    )

    def should_confirm(self, action: str) -> bool:
        """`False` once `remember_skip(action, ...)` has been called this
        session (or, for `"ever"`, in a past session too).
        """
        return action not in self._skipped_confirmations

    def remember_skip(self, action: str, scope: str) -> None:
        """`scope` is `"session"` (in-memory only, forgotten on quit) or
        `"ever"` (also written to the persisted config file, see
        `pyjjui.config`).
        """
        self._skipped_confirmations.add(action)
        if scope == "ever":
            pyjjui_config.persist_skip_confirmation(action)

    async def refresh(self) -> list[pyjj.GraphNode]:
        """Reload the repo at head and re-evaluate the current revset."""
        self.repo = await self.workspace.load_at_head_async()
        return await self.repo.log_graph_async(self.settings, self.revset)

    async def run_mutation(
        self,
        fn: Callable[..., pyjj.ReadonlyRepo],
        *args: Any,
    ) -> pyjj.ReadonlyRepo:
        """Run one of `mutations.py`'s functions on a worker thread.

        `Transaction`/`CommitBuilder` are `unsendable` on the Rust side
        (jj_lib's `MutableRepo` isn't `Send`), so the whole create-mutate-
        commit sequence in `fn` must happen as one synchronous unit on a
        single thread -- never split across an `await`, never handed a
        `Transaction` object from elsewhere. See `AGENTS.md`.
        """
        self.repo = await anyio.to_thread.run_sync(
            fn, self.workspace, self.repo, self.settings, *args
        )
        return self.repo
