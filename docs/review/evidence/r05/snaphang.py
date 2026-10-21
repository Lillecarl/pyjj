import sys
import tempfile
import time

import pyjj
import pyjj_bindings as b

base = sys.argv[1]
p = tempfile.mkdtemp(dir=base)
s = b.UserSettings()
b.Workspace.init_internal_git(s, p)
with open(p + "/a", "w") as f:
    f.write("a\n")
t = time.time()
r = pyjj.open(p)
print("open", time.time() - t, flush=True)
t = time.time()
try:
    r.snapshot()
except Exception as e:
    print("raised", type(e).__name__, e, getattr(e, "__cause__", None))
print("snap", time.time() - t, flush=True)
