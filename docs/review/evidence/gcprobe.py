"""gc(): panic on large cutoff; gc from a stale repo object with the default cutoff."""
import sys, tempfile
import pyjj_bindings as b
tmp = tempfile.mkdtemp(dir=sys.argv[1])
s = b.UserSettings(load_config=False).with_command_args(
    [("config", 'user.name="T"'), ("config", 'user.email="t@x"')])
ws, old = b.Workspace.init_internal_git(s, tmp)
for v in (float("inf"), 1e20):
    try:
        old.gc(v); print("gc", v, "ok")
    except BaseException as e:
        print("gc", v, "->", type(e).__name__, str(e)[:80])
tx = old.start_transaction(s)
root = old.resolve_single(s, "root()")
tx.new_commit(s, [root.id]).set_description("newer work").write(old)
new = tx.commit("newer op")
print("head op:", new.operation_id[:12])
old.gc()  # default cutoff, stale repo object
try:
    ws2 = b.Workspace.load(s, tmp)
    print("reload ok")
except BaseException as e:
    print("reload ->", type(e).__name__, str(e)[:160])
import os
print("ops on disk:", [n[:12] for n in os.listdir(os.path.join(tmp, ".jj/repo/op_store/operations"))])
try:
    r = ws2.load_at_head(); print("load_at_head ok", r.operation_id[:12])
except BaseException as e:
    print("load_at_head ->", type(e).__name__, str(e)[:200])
