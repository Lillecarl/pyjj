"""App-wide state: the loaded workspace/repo/settings, plus the mutation
entry point every widget must go through.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anyio.to_thread
import pyjj


@dataclass
class AppState:
    workspace: pyjj.Workspace
    settings: pyjj.UserSettings
    repo: pyjj.ReadonlyRepo
    revset: str

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
