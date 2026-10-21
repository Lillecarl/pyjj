"""Same lock-order probe as deadlock.py, with two plain threads and no event loop."""
import os
import sys
import tempfile
import threading

import pyjj_bindings as b

tmp = tempfile.mkdtemp(dir=sys.argv[1])
settings = b.UserSettings(load_config=False)
ws, repo = b.Workspace.init_internal_git(settings, tmp)
for i in range(3000):
    with open(os.path.join(tmp, f"f{i}.txt"), "w") as f:
        f.write(f"{i}\n" * 50)

done = threading.Event()
result = {}


def snap():
    result["stats"] = ws.snapshot(settings)[1]
    done.set()


t = threading.Thread(target=snap)
t.start()
reads = 0
while not done.is_set():
    _ = ws.workspace_root
    reads += 1
t.join()
print("finished", reads, dict(result["stats"]))
