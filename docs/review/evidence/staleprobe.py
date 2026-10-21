"""Stale working copy: does Workspace.snapshot revert a rewrite of @ made elsewhere?"""
import os, sys, tempfile
import pyjj_bindings as b
tmp = tempfile.mkdtemp(dir=sys.argv[1])
s = b.UserSettings(load_config=False).with_command_args(
    [("config", 'user.name="T"'), ("config", 'user.email="t@x"')])
ws, repo = b.Workspace.init_internal_git(s, tmp)
open(os.path.join(tmp, "f"), "w").write("f\n")
repo, st = ws.snapshot(s)
wc = repo.resolve_single(s, "@")
print("before:", wc.list_files())
# another process rewrites @ (adds g) without touching this working copy on disk
tx = repo.start_transaction(s)
tx.edit_commit_tree(wc, {"g": b"g\n"}).write(repo)
tx.rebase_descendants()
repo2 = tx.commit("other process adds g to @")
print("head @ after other op:", repo2.resolve_single(s, "@").list_files())
repo3, st = ws.snapshot(s)
print("snapshot stats:", st)
print("after pyjj snapshot:", repo3.resolve_single(s, "@").list_files())
