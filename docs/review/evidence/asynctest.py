"""Probe: the Rust *_async surface and the _async.py surface under asyncio, anyio-asyncio, anyio-trio.

Also probes: GIL held during a sync call (does a ticker thread advance?),
CommitId.short(99), TreeId hashability, IndexError shadowing.
"""
import sys
import tempfile
import threading
import time

import anyio
import pyjj_bindings as b
import pyjj  # noqa: F401  (installs Workspace.*_async)

tmp = tempfile.mkdtemp(dir=sys.argv[1])
settings = b.UserSettings(load_config=False)
ws, repo = b.Workspace.init_internal_git(settings, tmp)
root = repo.resolve_single(settings, "root()")


async def rust_async():
    c = await repo.resolve_single_async(settings, "root()")
    return await c.is_empty_async(repo)


async def py_async():
    w = await b.Workspace.load_async(settings, tmp) if hasattr(b.Workspace, "load_async") else None
    s = await ws.snapshot_async(settings) if False else None
    return w, s, hasattr(b.Workspace, "snapshot_async")


for label, runner in [
    ("asyncio", lambda f: __import__("asyncio").run(f())),
    ("anyio-asyncio", lambda f: anyio.run(f, backend="asyncio")),
    ("anyio-trio", lambda f: anyio.run(f, backend="trio")),
]:
    for fn in (rust_async, py_async):
        try:
            print(label, fn.__name__, "OK", runner(fn))
        except BaseException as e:
            print(label, fn.__name__, "FAIL", type(e).__name__, e)

ticks = 0
stop = False


def ticker():
    global ticks
    while not stop:
        ticks += 1
        time.sleep(0.0005)


t = threading.Thread(target=ticker)
t.start()
time.sleep(0.05)
before = ticks
t0 = time.perf_counter()
for _ in range(200):
    repo.revset(settings, "all()")
    root.is_empty(repo)
dt = time.perf_counter() - t0
mid = ticks
stop = True
t.join()
print(f"sync loop {dt*1000:.1f}ms, ticker advanced {mid-before} (expect ~{dt/0.0005:.0f} if GIL released)")

for probe in [
    lambda: root.id.short(99),
    lambda: hash(root.tree_id) if hasattr(root, "tree_id") else "no tree_id",
    lambda: hash(b.TreeId("0" * 40)),
    lambda: b.TreeId("0" * 40) == b.TreeId("0" * 40),
    lambda: b.CommitId("zz"),
    lambda: b.IndexError is IndexError,
    lambda: issubclass(b.IndexError, LookupError),
    lambda: repr(b.JjError("x")),
    lambda: str(b.RevsetParseError("boom")),
    lambda: b.RevsetParseError("boom").args,
]:
    try:
        print("probe", probe(), sep=": ")
    except BaseException as e:
        print("probe raised", type(e).__mro__, e)
