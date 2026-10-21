"""Which path strings does the binding accept into a tree?"""
import sys, tempfile
import pyjj_bindings as b
tmp = tempfile.mkdtemp(dir=sys.argv[1])
s = b.UserSettings(load_config=False).with_command_args(
    [("config", 'user.name="T"'), ("config", 'user.email="t@x"')])
ws, repo = b.Workspace.init_internal_git(s, tmp)
root = repo.resolve_single(s, "root()")
for p in ["", "..", "a/../b", ".", ".git/hooks/post-checkout", ".jj/repo/x"]:
    tx = repo.start_transaction(s)
    c = tx.new_commit(s, [root.id]).write(repo)
    try:
        c2 = tx.edit_commit_tree(c, {p: b"x\n"}).write(repo)
        print(repr(p), "-> accepted, files:", c2.list_files())
    except BaseException as e:
        print(repr(p), "->", type(e).__name__, str(e)[:100])
