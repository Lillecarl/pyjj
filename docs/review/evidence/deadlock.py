"""Probe: Workspace.snapshot_async (to_thread) + a getter on the loop thread.

snapshot holds the Workspace mutex inside py.detach and later re-attaches
(Python::attach) to build its stats dict. A getter that locks the mutex
while holding the GIL should deadlock against it.
Run under `timeout`; a hang is the positive result.
"""
import os
import sys
import tempfile

import anyio
import pyjj_bindings as b
import pyjj  # noqa: F401

tmp = tempfile.mkdtemp(dir=sys.argv[1])
settings = b.UserSettings(load_config=False)
ws, repo = b.Workspace.init_internal_git(settings, tmp)
for i in range(3000):
    with open(os.path.join(tmp, f"f{i}.txt"), "w") as f:
        f.write(f"{i}\n" * 50)


async def main():
    reads = 0

    async def spam():
        nonlocal reads
        while True:
            _ = ws.workspace_root
            reads += 1
            await anyio.sleep(0)

    async with anyio.create_task_group() as tg:
        tg.start_soon(spam)
        new_repo, stats = await ws.snapshot_async(settings)
        tg.cancel_scope.cancel()
    print("finished, reads during snapshot:", reads, dict(stats))


anyio.run(main)
